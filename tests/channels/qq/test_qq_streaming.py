# tests/channels/qq/test_qq_streaming.py
"""QQStreamingController 单元测试"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from illusion_forge.channels.base_streaming import StreamState
from illusion_forge.channels.qq.streaming import QQStreamingController
from illusion_forge.config.i18n import t as _t


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def mock_token():
    return "test_token"


@pytest.fixture
def mock_openid():
    return "test_openid"


@pytest.fixture
def mock_msg_id():
    return "test_msg_id"


@pytest.fixture
def controller(mock_session, mock_token, mock_openid, mock_msg_id):
    return QQStreamingController(
        session=mock_session,
        token=mock_token,
        openid=mock_openid,
        msg_id=mock_msg_id,
    )


@pytest.fixture
async def streaming_controller(controller):
    """返回已启动流式会话的控制器"""
    with patch("illusion_forge.channels.qq.streaming.send_c2c_stream_message") as mock_send:
        mock_send.return_value = {"id": "stream-123"}
        await controller.start()
    return controller


class TestQQStreamingControllerInit:
    def test_inherits_base(self, controller):
        from illusion_forge.channels.base_streaming import BaseStreamingController
        assert isinstance(controller, BaseStreamingController)

    def test_throttle_is_500ms(self, controller):
        assert controller._throttle_seconds == 0.5

    def test_initial_stream_msg_id_empty(self, controller):
        assert controller.stream_msg_id == ""


class TestQQDoFlush:
    @pytest.mark.asyncio
    async def test_first_flush_returns_stream_msg_id(self, controller):
        with patch("illusion_forge.channels.qq.streaming.send_c2c_stream_message") as mock_send:
            mock_send.return_value = {"id": "stream-123"}
            await controller._do_flush("hello", StreamState.GENERATING)

            mock_send.assert_called_once()
            assert controller.stream_msg_id == "stream-123"

    @pytest.mark.asyncio
    async def test_subsequent_flush_uses_stream_msg_id(self, controller):
        with patch("illusion_forge.channels.qq.streaming.send_c2c_stream_message") as mock_send:
            mock_send.return_value = {"id": "stream-123"}

            await controller._do_flush("first", StreamState.GENERATING)
            await controller._do_flush("second", StreamState.GENERATING)

            assert mock_send.call_count == 2
            # 第二次调用应包含 stream_msg_id
            second_call = mock_send.call_args_list[1]
            assert second_call.kwargs.get("stream_msg_id") == "stream-123"

    @pytest.mark.asyncio
    async def test_flush_without_id_raises(self, controller):
        with patch("illusion_forge.channels.qq.streaming.send_c2c_stream_message") as mock_send:
            mock_send.return_value = {}  # 无 id

            with pytest.raises(RuntimeError, match="缺少 id 字段"):
                await controller._do_flush("test", StreamState.GENERATING)


class TestQQDoFinalize:
    @pytest.mark.asyncio
    async def test_finalize_sends_done_state(self, controller):
        with patch("illusion_forge.channels.qq.streaming.send_c2c_stream_message") as mock_send:
            mock_send.return_value = {"id": "stream-123"}

            # 先 flush 一次获取 stream_msg_id
            await controller._do_flush("test", StreamState.GENERATING)
            await controller._do_finalize(is_error=False)

            # 最后一次调用应是 DONE 状态
            last_call = mock_send.call_args_list[-1]
            assert last_call.kwargs.get("input_state") == 10  # DONE


class TestQQReasoningSupport:
    @pytest.mark.asyncio
    async def test_reasoning_accumulates(self, streaming_controller):
        await streaming_controller.on_reasoning("thinking...")
        assert streaming_controller.reasoning_text == "thinking..."
        assert streaming_controller.is_reasoning_phase is True

    @pytest.mark.asyncio
    async def test_reasoning_shows_in_display(self, streaming_controller):
        await streaming_controller.on_reasoning("thinking...")
        display = streaming_controller._build_display_text()
        thinking_header = _t("streaming_thinking")
        assert thinking_header in display
        assert "thinking..." in display

    @pytest.mark.asyncio
    async def test_text_freezes_reasoning_snapshot(self, streaming_controller):
        """text 到达后冻结 reasoning 快照，display text 使用快照（前缀兼容）"""
        await streaming_controller.on_reasoning("thinking")
        await streaming_controller.on_text("answer")

        assert streaming_controller.is_reasoning_phase is False
        assert streaming_controller._reasoning_snapshot == "thinking"
        display = streaming_controller._build_display_text()
        thinking_header = _t("streaming_thinking")
        assert display == f"{thinking_header}\n\nthinking\n\n---\n\nanswer"

    @pytest.mark.asyncio
    async def test_new_reasoning_after_text_uses_snapshot(self, streaming_controller):
        """tool_call 后新 reasoning 不改变 display text（避免 40007 前缀冲突）"""
        await streaming_controller.on_reasoning("original")
        await streaming_controller.on_text("answer")
        # 模拟 tool_call 后的新 reasoning
        await streaming_controller.on_reasoning("new reasoning")

        display = streaming_controller._build_display_text()
        thinking_header = _t("streaming_thinking")
        # display text 使用冻结的快照，不包含 new reasoning
        assert display == f"{thinking_header}\n\noriginal\n\n---\n\nanswer"
        # 但 _reasoning_text 包含全部 reasoning（用于终态卡片）
        assert "new reasoning" in streaming_controller.reasoning_text
