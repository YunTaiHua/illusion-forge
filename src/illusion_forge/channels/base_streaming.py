"""流式控制器公共基类

提供状态机管理、文本累积、节流调度和 reasoning 显示逻辑。
子类只需实现 _do_flush() 和 _do_finalize()。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Coroutine
from enum import Enum
from typing import Any, ClassVar

from illusion_forge.config.i18n import t as _t

logger = logging.getLogger(__name__)


class StreamState(Enum):
    """流式消息状态"""
    GENERATING = 1  # 生成中
    DONE = 10       # 生成结束


class BaseStreamingController:
    """流式控制器公共基类

    子类只需实现:
    - _do_flush(text: str, state: StreamState) -> None: 实际发送内容
    - _do_finalize(is_error: bool) -> None: 终态收尾
    """

    # 子类可覆盖的节流间隔（秒）
    _throttle_seconds: float = 0.5

    # 状态机转换表
    _TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        "idle": {"streaming", "completed", "aborted"},
        "streaming": {"completed", "aborted"},
        "completed": set(),
        "aborted": set(),
    }

    def __init__(self, *, show_reasoning: bool = True) -> None:
        # 状态机
        self._phase: str = "idle"

        # 文本累积
        self._accumulated_text: str = ""
        self._reasoning_text: str = ""
        self._is_reasoning_phase: bool = False
        self._show_reasoning: bool = show_reasoning  # 是否显示思考过程

        # reasoning 快照：首次 text 到达时冻结当时的 reasoning 内容，
        # 防止后续新 reasoning（tool_call 后）改变 display text 中间部分，
        # 从而避免 QQ stream_messages 前缀冲突（40007 错误）和飞书闪烁。
        # None 表示尚未冻结（还在 reasoning 阶段）。
        self._reasoning_snapshot: str | None = None

        # 节流
        self._last_flush_time: float = 0.0
        self._pending_timer: asyncio.TimerHandle | None = None
        self._flush_in_progress: bool = False
        self._needs_reflush: bool = False
        self._started: bool = False
        self._is_first_flush: bool = True  # 首次 flush 不走节流

        # 去重
        self._last_flushed_text: str = ""

        # 统计
        self._sent_chunk_count: int = 0

        # fire-and-forget task 引用
        self._dispatch_tasks: set[asyncio.Task[None]] = set()

    # --- 公开属性 ---

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def accumulated_text(self) -> str:
        return self._accumulated_text

    @property
    def reasoning_text(self) -> str:
        return self._reasoning_text

    @property
    def is_reasoning_phase(self) -> bool:
        return self._is_reasoning_phase

    @property
    def should_fallback_to_static(self) -> bool:
        """是否应降级到普通静态消息发送"""
        return self._phase in ("completed", "aborted") and self._sent_chunk_count == 0

    # --- 公开接口 ---

    async def start(self) -> None:
        """启动流式会话，发送初始 "💭 Thinking..." 指示器

        在消息处理开始时调用，让用户立即看到思考状态。
        子类应实现 `_do_start()` 来发送初始内容。
        """
        if self._phase == "streaming":
            return
        if not self._transition("streaming"):
            return
        self._started = True
        self._is_first_flush = False  # 首次 flush 已用于发送初始内容
        self._last_flush_time = time.monotonic()
        await self._do_start()

    async def on_reasoning(self, reasoning: str) -> None:
        """处理思考增量"""
        if self._phase != "streaming":
            return
        if not reasoning:
            return
        self._is_reasoning_phase = True
        self._reasoning_text += reasoning
        await self._throttled_flush()

    async def on_text(self, text: str) -> None:
        """处理文本增量

        首次 text 到达时冻结 reasoning 快照（_reasoning_snapshot），
        后续新 reasoning 不再改变流式 display text 的 reasoning 部分，
        确保 display text 严格递增（QQ replace 模式前缀兼容）。
        """
        if self._phase != "streaming":
            return
        if not text:
            return
        if self._is_reasoning_phase:
            self._is_reasoning_phase = False
            # 首次 text 到达时冻结 reasoning 快照（仅冻结一次）
            if self._reasoning_snapshot is None:
                self._reasoning_snapshot = self._reasoning_text
        self._accumulated_text += text
        await self._throttled_flush()

    async def complete(self) -> None:
        """完成流式，发送终结分片"""
        if not self._transition("completed"):
            return
        await self._finalize(is_error=False)

    async def abort(self, reason: str = "") -> None:
        """中止流式"""
        if not self._transition("aborted"):
            return
        if reason:
            logger.info("%s 流式中止: %s", self.__class__.__name__, reason)
        self._cancel_pending_flush()

    # --- 状态机 ---

    def _transition(self, new_phase: str) -> bool:
        """尝试状态转换，非法转换返回 False"""
        if new_phase in self._TRANSITIONS.get(self._phase, set()):
            old = self._phase
            self._phase = new_phase
            logger.debug("流式状态转换: %s → %s", old, new_phase)
            return True
        logger.warning("非法状态转换: %s → %s（拒绝）", self._phase, new_phase)
        return False

    # --- Reasoning 显示逻辑 ---

    def _build_display_text(self) -> str:
        """构造流式显示文本

        分阶段显示策略（通过 _reasoning_snapshot 保证 display text 严格递增）：

        reasoning 阶段（snapshot 未冻结）：
            {thinking_header}\\n\\n{reasoning}（reasoning 持续增长）

        text 阶段（snapshot 已冻结）：
            {thinking_header}\\n\\n{frozen_reasoning}\\n\\n---\\n\\n{text}（text 持续增长）

        关键：text 阶段使用冻结的 reasoning 快照而非实时 _reasoning_text，
        确保后续新 reasoning（tool_call 后）不改变 display text 中间部分，
        从而避免 QQ stream_messages 40007 前缀冲突和飞书闪烁。

        当 show_reasoning=False 时，只显示答案。
        """
        # text 阶段：使用冻结的 reasoning 快照
        if self._accumulated_text:
            snapshot = self._reasoning_snapshot
            if self._show_reasoning and snapshot:
                thinking_header = _t("streaming_thinking")
                return f"{thinking_header}\n\n{snapshot}\n\n---\n\n{self._accumulated_text}"
            return self._accumulated_text
        # reasoning 阶段：使用实时 reasoning
        if self._show_reasoning and self._reasoning_text:
            thinking_header = _t("streaming_thinking")
            return f"{thinking_header}\n\n{self._reasoning_text}"
        return ""

    # --- 节流 flush ---

    async def _throttled_flush(self) -> None:
        """节流更新调度"""
        if self._phase != "streaming":
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

        now = time.monotonic()
        elapsed = now - self._last_flush_time

        if elapsed >= self._throttle_seconds:
            self._cancel_pending_flush()
            await self._flush()
        else:
            if self._pending_timer is None:
                delay = self._throttle_seconds - elapsed
                self._schedule_delayed_flush(delay)

    def _schedule_delayed_flush(self, delay: float) -> None:
        """调度延迟 flush"""
        if self._pending_timer is not None:
            return
        loop = asyncio.get_running_loop()
        self._pending_timer = loop.call_later(delay, self._delayed_flush_callback)

    def _delayed_flush_callback(self) -> None:
        """call_later 回调"""
        self._pending_timer = None
        self._create_background_task(self._delayed_flush_task())

    def _create_background_task(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        """创建 fire-and-forget task 并保留强引用"""
        task = asyncio.create_task(coro)
        self._dispatch_tasks.add(task)
        task.add_done_callback(self._dispatch_tasks.discard)
        return task

    async def _delayed_flush_task(self) -> None:
        """延迟 flush 任务"""
        if self._phase != "streaming":
            return
        await self._flush()

    def _cancel_pending_flush(self) -> None:
        """取消 pending 的延迟 flush timer"""
        if self._pending_timer is not None:
            self._pending_timer.cancel()
            self._pending_timer = None

    async def _flush(self, *, force: bool = False) -> None:
        """执行 flush（互斥 + needsReflush 补偿 + 文本去重）

        force=True 时绕过相位检查，用于终态收尾时发送剩余文本。
        """
        if self._flush_in_progress or (self._phase != "streaming" and not force):
            if self._flush_in_progress:
                self._needs_reflush = True
            return

        display_text = self._build_display_text()

        if display_text == self._last_flushed_text:
            return

        self._flush_in_progress = True
        self._needs_reflush = False
        self._last_flush_time = time.monotonic()
        try:
            await self._do_flush(display_text, StreamState.GENERATING)
            self._sent_chunk_count += 1
            self._last_flushed_text = display_text
        except (RuntimeError, ValueError, KeyError) as exc:
            logger.warning("流式 flush 失败: %s", exc)
        except (OSError, ConnectionError, TimeoutError) as exc:
            # 服务器断开连接等网络错误，降级为 debug 日志（关闭渠道时常见）
            logger.debug("流式 flush 网络错误（可忽略）: %s", exc)
        finally:
            self._flush_in_progress = False
            self._last_flush_time = time.monotonic()
            if (
                self._needs_reflush
                and self._phase == "streaming"
                and self._pending_timer is None
            ):
                self._needs_reflush = False
                self._schedule_delayed_flush(0)

    async def _finalize(self, *, is_error: bool) -> None:
        """终态收尾"""
        self._cancel_pending_flush()

        while self._flush_in_progress:
            await asyncio.sleep(0.01)

        if self._sent_chunk_count == 0:
            return

        self._is_reasoning_phase = False
        # 最终 flush：发送所有累积文本（绕过节流和相位检查）
        await self._flush(force=True)
        await self._do_finalize(is_error)

    # --- 子类必须实现的抽象方法 ---

    async def _do_start(self) -> None:
        """发送初始 "💭 Thinking..." 指示器（子类实现）

        在 `start()` 方法中调用，用于创建流式会话并发送初始内容。
        """
        raise NotImplementedError

    async def _do_flush(self, text: str, state: StreamState) -> None:
        """实际发送内容到渠道 API（子类实现）"""
        raise NotImplementedError

    async def _do_finalize(self, is_error: bool) -> None:
        """终态收尾（子类实现）"""
        raise NotImplementedError
