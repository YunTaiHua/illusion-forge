"""飞书 CardKit 流式卡片控制器

管理单条飞书消息的流式卡片生命周期：
- 创建流式卡片（CardKit card.create + im.message.create）
- 节流更新 element（cardElement.content，100ms 间隔）
- 终态收尾：先 card.settings 关闭 streaming_mode，再 card.update 全卡替换
- CardKit 失败时降级到 patch_card（1500ms 节流）

状态机（5 态）：
    idle → creating → streaming → completed / error

继承自 BaseStreamingController，复用状态机、节流调度和 reasoning 显示逻辑。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from illusion_forge.channels.base_streaming import BaseStreamingController, StreamState
from illusion_forge.channels.feishu.messaging import (
    STREAMING_ELEMENT_ID,
    build_complete_card,
    build_streaming_card,
    create_card_entity,
    patch_card,
    send_card_by_card_id,
    set_card_streaming_mode,
    stream_card_element_content,
    update_cardkit_card,
)
from illusion_forge.config.i18n import t as _t

logger = logging.getLogger(__name__)

# 长间隔阈值
_LONG_GAP_THRESHOLD_S = 2.0
_BATCH_AFTER_GAP_S = 0.3

# 合法状态转换（扩展基类，增加 creating / error 状态）
_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"creating"},
    "creating": {"streaming", "error"},
    "streaming": {"completed", "error"},
    "completed": set(),
    "error": set(),
}


class FeishuStreamingCardController(BaseStreamingController):
    """管理单条飞书消息的流式卡片生命周期"""

    # 节流间隔（秒）
    _throttle_seconds = 0.1       # CardKit: 100ms
    _throttle_patch_seconds = 1.5  # patch 降级: 1500ms

    # 状态机转换表
    _TRANSITIONS = _TRANSITIONS

    def __init__(
        self,
        client: Any,
        chat_id: str,
        *,
        reply_to: str = "",
        show_reasoning: bool = True,
    ) -> None:
        super().__init__(show_reasoning=show_reasoning)
        self._client = client
        self._chat_id = chat_id
        self._reply_to = reply_to

        # CardKit 资源
        self._message_id: str | None = None
        self._card_id: str = ""  # 空字符串表示 CardKit 不可用，走 patch 降级

        # 节流
        self._sequence: int = 0
        self._card_message_ready: bool = False

        # 计时
        self._start_time: float = 0.0
        self._reasoning_start_time: float = 0.0
        self._reasoning_elapsed_ms: int = 0

    # --- 公开属性 ---

    @property
    def message_id(self) -> str:
        return self._message_id or ""

    @property
    def card_id(self) -> str:
        return self._card_id

    # --- 生命周期入口 ---

    async def start(self) -> None:
        """创建流式卡片，进入 streaming 状态

        尝试 CardKit 路径，失败时降级到 patch 路径。
        然后发送初始 "💭 Thinking..." 指示器。
        """
        if not self._transition("creating"):
            return

        self._start_time = time.monotonic()

        # 尝试 CardKit 路径
        card_content = build_streaming_card()
        card_id = await create_card_entity(self._client, card_content)

        if card_id:
            # CardKit 成功，通过 card_id 发送消息
            try:
                message_id = await send_card_by_card_id(
                    self._client, self._chat_id, card_id, reply_to=self._reply_to,
                )
                self._card_id = card_id
                self._message_id = message_id
                self._transition("streaming")
                self._card_message_ready = True
                self._last_flush_time = time.monotonic()
                # 发送初始 "💭 Thinking..." 指示器
                await self._do_start()
                return
            except RuntimeError as exc:
                logger.warning("CardKit 消息发送失败，降级到 patch: %s", exc)

        # 降级到 patch 路径：发送普通卡片
        from illusion_forge.channels.feishu.messaging import send_card

        try:
            # 使用与 CardKit 路径一致的 "💭 Thinking..." 格式
            thinking_text = _t("streaming_thinking") if self._show_reasoning else "⏳"
            self._message_id = await send_card(
                self._client, self._chat_id, thinking_text,
                reply_to=self._reply_to,
            )
            self._card_id = ""  # 标记 CardKit 不可用
            self._transition("streaming")
            self._card_message_ready = True
            self._last_flush_time = time.monotonic()
            # 降级路径已发送初始内容，无需再调用 _do_start()
        except (RuntimeError, AttributeError, OSError) as exc:
            logger.error("降级路径也失败: %s", exc)
            self._transition("error")

    async def _do_start(self) -> None:
        """发送初始 "💭 Thinking..." 指示器到飞书卡片"""
        if self._show_reasoning:
            # 更新卡片内容为 "💭 Thinking..."
            initial_text = _t("streaming_thinking")
            await self._do_flush(initial_text, StreamState.GENERATING)
            self._last_flushed_text = initial_text
            self._sent_chunk_count += 1

    # --- 流式回调 ---

    async def on_reasoning(self, reasoning: str) -> None:
        """处理思考增量"""
        if self._phase != "streaming":
            return
        if not reasoning:
            return
        if self._reasoning_start_time == 0:
            self._reasoning_start_time = time.monotonic()
        self._is_reasoning_phase = True
        self._reasoning_text += reasoning
        await self._throttled_flush()

    async def on_text(self, text: str) -> None:
        """处理文本增量

        首个 text 到达时重置 is_reasoning_phase，避免思考前缀残留到答案阶段。
        """
        if self._phase != "streaming":
            return
        if not text:
            return
        if self._is_reasoning_phase:
            self._is_reasoning_phase = False
            if self._reasoning_start_time > 0:
                self._reasoning_elapsed_ms = int(
                    (time.monotonic() - self._reasoning_start_time) * 1000
                )
        self._accumulated_text += text
        await self._throttled_flush()

    # --- 终态 ---

    async def complete(self) -> None:
        """完成流式，全卡替换为终态"""
        if not self._transition("completed"):
            return
        await self._finalize(is_error=False)

    async def error(self, error_msg: str = "") -> None:
        """错误终态"""
        if not self._transition("error"):
            return
        if error_msg:
            self._accumulated_text += f"\n\n---\n**Error**: {error_msg}"
        await self._finalize(is_error=True)

    # --- 节流 flush ---

    async def _throttled_flush(self) -> None:
        """节流更新 streaming_content element

        CardKit 路径用 100ms 节流，patch 降级路径用 1500ms 节流。
        长间隔（>2s）后延迟 300ms 批量 flush，避免首帧只显示 1-2 个字符。
        """
        if not self._card_message_ready or self._phase != "streaming":
            return

        # 首次 flush 直接执行，不走节流
        if self._is_first_flush:
            self._cancel_pending_flush()
            # 记录 flush 前的文本，用于判断 flush 是否实际发送了内容
            text_before_flush = self._last_flushed_text
            await self._flush()
            # 仅在 flush 实际发送了内容后才消费首次标志（避免空 flush 消耗标志）
            if self._last_flushed_text != text_before_flush:
                self._is_first_flush = False
            return

        throttle = self._throttle_seconds if self._card_id else self._throttle_patch_seconds
        now = time.monotonic()
        elapsed = now - self._last_flush_time

        if elapsed >= throttle:
            self._cancel_pending_flush()
            if elapsed > _LONG_GAP_THRESHOLD_S and self._last_flush_time > 0:
                # 长间隔后延迟批量，避免首帧只显示 1-2 个字符
                # 关键：更新 last_flush_time，让批量窗口内的后续事件进入节流窗口分支
                self._last_flush_time = now
                self._schedule_delayed_flush(_BATCH_AFTER_GAP_S)
            else:
                await self._flush()
        else:
            # 节流窗口内：调度延迟 flush（已有 pending 则不重复调度）
            if self._pending_timer is None:
                delay = throttle - elapsed
                self._schedule_delayed_flush(delay)

    # --- 终态收尾 ---

    async def _finalize(self, *, is_error: bool) -> None:
        """终态收尾：先关闭流式模式，再全卡替换

        与基类不同，Feishu 始终需要收尾（即使 sent_chunk_count == 0），
        因为卡片必须被关闭流式模式并替换为终态。
        """
        # 取消 pending flush timer
        self._cancel_pending_flush()

        # 等待进行中的 flush 完成
        while self._flush_in_progress:
            await asyncio.sleep(0.01)

        # 重置思考阶段标志，避免终态卡片残留思考前缀
        self._is_reasoning_phase = False

        await self._do_finalize(is_error)

    # --- 子类必须实现的抽象方法 ---

    async def _do_flush(self, text: str, state: StreamState) -> None:
        """实际发送内容到飞书 API

        CardKit 路径：增量更新 element（stream_card_element_content）
        patch 降级路径：全卡替换（patch_card）
        """
        # 净化图片 URL（避免飞书 200570 错误）
        from illusion_forge.channels.feishu.messaging import _sanitize_card_text
        text = _sanitize_card_text(text)

        if self._card_id:
            # CardKit 路径：增量更新 element
            self._sequence += 1
            ok = await stream_card_element_content(
                self._client,
                self._card_id,
                STREAMING_ELEMENT_ID,
                text,
                self._sequence,
            )
            if not ok:
                logger.warning("CardKit 流式更新失败（跳帧）: seq=%d", self._sequence)
        elif self._message_id:
            # patch 降级路径：全卡替换
            await patch_card(self._client, self._message_id, text)

    async def _do_finalize(self, is_error: bool) -> None:
        """终态收尾：关闭流式模式 + 全卡替换

        1. set_card_streaming_mode(False) 关闭流式态（关键！）
        2. update_cardkit_card 全卡替换为终态卡片
        3. 失败时降级到 patch_card
        """
        elapsed_ms = int((time.monotonic() - self._start_time) * 1000)

        if self._card_id:
            # 步骤 1：关闭流式模式（必须先于全卡替换）
            self._sequence += 1
            streaming_ok = await set_card_streaming_mode(
                self._client, self._card_id, False, self._sequence,
            )
            if not streaming_ok:
                logger.warning("关闭流式模式失败，继续尝试全卡替换")

            # 步骤 2：全卡替换为终态卡片
            card_content = build_complete_card(
                text=self._accumulated_text,
                reasoning_text=self._reasoning_text,
                elapsed_ms=elapsed_ms,
                is_error=is_error,
                show_reasoning=self._show_reasoning,
            )
            self._sequence += 1
            ok = await update_cardkit_card(
                self._client, self._card_id, card_content, self._sequence,
            )
            if not ok and self._message_id:
                # card.update 失败，降级到 patch_card（传纯文本，不是 JSON）
                logger.warning("card.update 失败，降级到 patch_card")
                await patch_card(self._client, self._message_id, self._accumulated_text)
        else:
            # patch 降级路径：传纯 markdown 文本（patch_card 内部会包装成卡片）
            if self._message_id:
                await patch_card(self._client, self._message_id, self._accumulated_text)
