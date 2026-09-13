"""QQ C2C 流式消息控制器单元测试

覆盖：
- send_c2c_stream_message API 封装（请求体构造、stream_msg_id 复用、响应解析）
- QQStreamingController 状态机（idle → streaming → completed/aborted）
- 首次启动流程（stream_msg_id 获取）
- reasoning 快照冻结机制（前缀冲突防护）
- 节流 flush（500ms 间隔、长间隔批量、去重）
- 终态收尾（input_state=DONE 分片）
- 降级策略（should_fallback_to_static）
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

aiohttp = pytest.importorskip("aiohttp")

from illusion_forge.channels.qq.api import (
    STREAM_INPUT_MODE_REPLACE,
    STREAM_INPUT_STATE_DONE,
    STREAM_INPUT_STATE_GENERATING,
    send_c2c_stream_message,
)
from illusion_forge.channels.qq.streaming import QQStreamingController

# ─── 辅助函数 ──────────────────────────────────────────────


def _mock_response(data: dict | None = None) -> MagicMock:
    """构造模拟 aiohttp 响应"""
    resp = MagicMock()
    resp.status = 200
    if data is None:
        resp.text = AsyncMock(return_value="")
        resp.json = AsyncMock(return_value={})
    else:
        import json
        resp.text = AsyncMock(return_value=json.dumps(data))
        resp.json = AsyncMock(return_value=data)
    return resp


def _mock_session(response_data: dict | None = None) -> MagicMock:
    """构造模拟 aiohttp.ClientSession"""
    session = MagicMock()
    resp = _mock_response(response_data or {"id": "smid_123"})
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=None)
    session.post = MagicMock(return_value=ctx)
    return session


# ─── API 封装测试 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_c2c_stream_message_first_chunk() -> None:
    """首次分片：不传 stream_msg_id"""
    session = _mock_session({"id": "smid_123"})
    resp = await send_c2c_stream_message(
        session, "token_abc", "openid_xyz",
        content="Hello",
        input_state=STREAM_INPUT_STATE_GENERATING,
        msg_id="msg_in_001",
        msg_seq=42,
        index=1,
    )
    assert resp["id"] == "smid_123"
    session.post.assert_called_once()
    body = session.post.call_args[1]["json"]
    assert body["input_mode"] == STREAM_INPUT_MODE_REPLACE
    assert body["content_raw"] == "Hello"
    assert "stream_msg_id" not in body


@pytest.mark.asyncio
async def test_send_c2c_stream_message_done_state() -> None:
    """终结分片：input_state=DONE"""
    session = _mock_session({})
    await send_c2c_stream_message(
        session, "token_abc", "openid_xyz",
        content="Final text",
        input_state=STREAM_INPUT_STATE_DONE,
        msg_id="msg_in_001",
        msg_seq=42,
        index=5,
        stream_msg_id="smid_123",
    )
    body = session.post.call_args[1]["json"]
    assert body["input_state"] == STREAM_INPUT_STATE_DONE


# ─── Controller 状态机测试 ─────────────────────────────────


@pytest.mark.asyncio
async def test_controller_initial_state() -> None:
    """初始状态"""
    session = _mock_session()
    controller = QQStreamingController(
        session=session, token="token_abc", openid="openid_xyz",
        msg_id="msg_001",
    )
    assert controller.phase == "idle"
    assert controller.stream_msg_id == ""


@pytest.mark.asyncio
async def test_controller_start_sends_initial_content() -> None:
    """start() 发送初始 "💭 思考中..." 分片并获取 stream_msg_id"""
    session = _mock_session({"id": "smid_abc"})
    controller = QQStreamingController(
        session=session, token="token_abc", openid="openid_xyz",
        msg_id="msg_001",
    )
    await controller.start()
    assert controller.phase == "streaming"
    assert controller.stream_msg_id == "smid_abc"
    assert session.post.call_count == 1
    body = session.post.call_args[1]["json"]
    assert body["index"] == 0


@pytest.mark.asyncio
async def test_controller_ignores_empty_text() -> None:
    """空文本不触发启动"""
    session = _mock_session()
    controller = QQStreamingController(
        session=session, token="token_abc", openid="openid_xyz",
        msg_id="msg_001",
    )
    await controller.on_text("")
    await controller.on_text("   ")
    assert controller.phase == "idle"
    assert session.post.call_count == 0


@pytest.mark.asyncio
async def test_controller_complete_sends_done_chunk() -> None:
    """complete() 发送 DONE 分片"""
    session = _mock_session({"id": "smid_abc"})
    controller = QQStreamingController(
        session=session, token="token_abc", openid="openid_xyz",
        msg_id="msg_001",
    )
    await controller.start()
    await controller.on_text("Hello")
    await asyncio.sleep(0.6)
    count_before = session.post.call_count
    await controller.complete()
    assert controller.phase == "completed"
    assert session.post.call_count == count_before + 1
    last_body = session.post.call_args[1]["json"]
    assert last_body["input_state"] == STREAM_INPUT_STATE_DONE


@pytest.mark.asyncio
async def test_controller_complete_without_chunk_falls_back() -> None:
    """complete() 时从未发过分片 → fallback"""
    session = _mock_session({"id": "smid_abc"})
    controller = QQStreamingController(
        session=session, token="token_abc", openid="openid_xyz",
        msg_id="msg_001", show_reasoning=False,  # 不发送初始内容
    )
    await controller.start()  # show_reasoning=False, 不发送
    await controller.complete()
    assert controller.should_fallback_to_static is True


@pytest.mark.asyncio
async def test_controller_abort_does_not_send_done() -> None:
    """abort() 不发 DONE 分片"""
    session = _mock_session({"id": "smid_abc"})
    controller = QQStreamingController(
        session=session, token="token_abc", openid="openid_xyz",
        msg_id="msg_001",
    )
    await controller.start()
    await controller.on_text("Hello")
    await asyncio.sleep(0.6)
    count_before = session.post.call_count
    await controller.abort("user cancelled")
    assert controller.phase == "aborted"
    assert session.post.call_count == count_before


# ─── reasoning 快照冻结测试 ────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_snapshot_frozen_on_first_text() -> None:
    """首次 text 到达时冻结 reasoning 快照"""
    session = _mock_session({"id": "smid_snap"})
    controller = QQStreamingController(
        session=session, token="t", openid="o", msg_id="m",
    )
    await controller.start()
    await controller.on_reasoning("initial reasoning")
    assert controller._reasoning_snapshot is None  # 尚未冻结

    await controller.on_text("answer")
    assert controller._reasoning_snapshot == "initial reasoning"


@pytest.mark.asyncio
async def test_snapshot_prevents_prefix_conflict() -> None:
    """快照机制确保 display text 在 tool_call 后新 reasoning 时不改变中间部分"""
    session = _mock_session({"id": "smid_prefix"})
    controller = QQStreamingController(
        session=session, token="t", openid="o", msg_id="m",
    )
    await controller.start()
    await controller.on_reasoning("R1")
    await controller.on_text("T1")
    display_before = controller._build_display_text()

    # 模拟 tool_call 后新 reasoning
    await controller.on_reasoning("R2")
    await controller.on_text("T2")
    display_after = controller._build_display_text()

    # display_after 必须以 display_before 为前缀（QQ replace 模式要求）
    assert display_after.startswith(display_before), (
        f"display text 前缀冲突！\nbefore: {display_before!r}\nafter: {display_after!r}"
    )
    # 但 _reasoning_text 包含全部 reasoning
    assert "R2" in controller.reasoning_text


# ─── 集成测试 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_integration_full_streaming_flow() -> None:
    """完整流式流程：启动 → reasoning → text → 终结"""
    session = _mock_session({"id": "smid_integration"})
    controller = QQStreamingController(
        session=session, token="token_abc", openid="openid_xyz",
        msg_id="msg_001",
    )

    await controller.start()
    await controller.on_reasoning("Let me think")
    for chunk in ["Hello", " world", "!"]:
        await controller.on_text(chunk)
        await asyncio.sleep(0.05)

    await asyncio.sleep(0.7)
    await controller.complete()
    assert controller.phase == "completed"
    assert controller.should_fallback_to_static is False
    assert controller.accumulated_text == "Hello world!"
    last_body = session.post.call_args[1]["json"]
    assert last_body["input_state"] == STREAM_INPUT_STATE_DONE
