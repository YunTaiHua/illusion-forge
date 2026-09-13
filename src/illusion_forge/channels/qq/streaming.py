# src/illusion_forge/channels/qq/streaming.py
"""QQ C2C 流式消息控制器

管理单条 QQ C2C 消息的流式生命周期，通过 QQ 开放平台
`/v2/users/{openid}/stream_messages` API 实现打字机效果。

支持思考过程流式展示（与飞书体验一致）。

前缀冲突防护：
QQ stream_messages 使用 replace 模式，要求新内容必须以已下发内容为前缀。
基类 BaseStreamingController 通过 _reasoning_snapshot 机制确保 display text
严格递增：首次 text 到达时冻结 reasoning 快照，后续新 reasoning 不改变
流式 display text 的中间部分，从而避免 40007 错误。
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from illusion_forge.channels.base_streaming import BaseStreamingController, StreamState
from illusion_forge.channels.qq.api import (
    STREAM_INPUT_STATE_DONE,
    STREAM_INPUT_STATE_GENERATING,
    _next_msg_seq,
    send_c2c_stream_message,
)
from illusion_forge.config.i18n import t as _t

logger = logging.getLogger(__name__)


class QQStreamingController(BaseStreamingController):
    """QQ C2C 流式控制器

    使用 QQ 开放平台 /v2/users/{openid}/stream_messages API 实现打字机效果。
    支持思考过程流式展示。

    仅支持 C2C 私聊场景。群聊不支持 stream_messages API，由上层走普通发送。
    """

    _throttle_seconds = 0.5  # QQ 500ms 节流

    def __init__(
        self,
        session: Any,
        token: str,
        openid: str,
        *,
        msg_id: str,
        show_reasoning: bool = True,
    ) -> None:
        super().__init__(show_reasoning=show_reasoning)
        self._session = session
        self._token = token
        self._openid = openid
        self._msg_id = msg_id

        # 流式会话资源
        self._stream_msg_id: str = ""
        self._msg_seq: int = _next_msg_seq()
        self._index: int = 0

    @property
    def stream_msg_id(self) -> str:
        return self._stream_msg_id

    async def _do_start(self) -> None:
        """发送初始 "💭 Thinking..." 指示器到 QQ"""
        if self._show_reasoning:
            # 发送第一个分片 "💭 Thinking..."
            initial_text = _t("streaming_thinking")
            await self._do_flush(initial_text, StreamState.GENERATING)
            self._last_flushed_text = initial_text
            self._sent_chunk_count += 1

    async def _do_flush(self, text: str, state: StreamState) -> None:
        """调用 QQ stream_messages API"""
        try:
            resp = await send_c2c_stream_message(
                self._session,
                self._token,
                self._openid,
                content=text,
                input_state=STREAM_INPUT_STATE_GENERATING,
                msg_id=self._msg_id,
                msg_seq=self._msg_seq,
                index=self._index,
                stream_msg_id=self._stream_msg_id,
                event_id=self._msg_id,
            )
            # 首帧返回 stream_msg_id
            if not self._stream_msg_id:
                stream_msg_id = str(resp.get("id", "") or "")
                if not stream_msg_id:
                    raise RuntimeError(f"QQ stream_messages 响应缺少 id 字段: {resp}")
                self._stream_msg_id = stream_msg_id
            self._index += 1
        except (aiohttp.ClientError, RuntimeError, ValueError, KeyError) as exc:
            logger.warning("QQ 流式 flush 失败: %s", exc)
            raise

    async def _do_finalize(self, is_error: bool) -> None:
        """发送终结分片（input_state=DONE）

        使用 _build_display_text() 保持与流式过程一致的内容。
        display text 通过 _reasoning_snapshot 机制保证前缀一致性。
        """
        try:
            # 使用和流式过程相同的显示文本，保持前缀一致
            display_text = self._build_display_text()
            await send_c2c_stream_message(
                self._session,
                self._token,
                self._openid,
                content=display_text,
                input_state=STREAM_INPUT_STATE_DONE,
                msg_id=self._msg_id,
                msg_seq=self._msg_seq,
                index=self._index,
                stream_msg_id=self._stream_msg_id,
                event_id=self._msg_id,
            )
            logger.info(
                "QQ 流式已完成: stream_msg_id=%s 总分片数=%d",
                self._stream_msg_id, self._sent_chunk_count,
            )
        except (aiohttp.ClientError, RuntimeError, ValueError, KeyError) as exc:
            logger.warning("QQ 流式终结分片发送失败: %s", exc)
