# tests/channels/test_integration.py
"""集成测试：验证 QQ 推理流式完整流程

测试场景：
1. QQ 完整 reasoning→answer 流程
2. QQ 流式启动失败时的 fallback
3. 飞书行为无回归
4. 基类单元测试仍通过
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from illusion_forge.channels.base_streaming import BaseStreamingController, StreamState
from illusion_forge.channels.qq.streaming import QQStreamingController
from illusion_forge.config.i18n import t as _t


# ---------------------------------------------------------------------------
# 辅助：具体化基类用于测试
# ---------------------------------------------------------------------------

class ConcreteStreamingController(BaseStreamingController):
    """测试用具体实现，记录所有 flush/finalize 调用"""

    def __init__(self):
        super().__init__()
        self.flush_calls: list[tuple[str, StreamState]] = []
        self.finalize_calls: list[bool] = []

    async def _do_flush(self, text: str, state: StreamState) -> None:
        self.flush_calls.append((text, state))

    async def _do_start(self) -> None:
        # 模拟发送初始思考内容（使用 i18n 文本）
        self._sent_chunk_count += 1
        self._last_flushed_text = _t("streaming_thinking")

    async def _do_finalize(self, is_error: bool) -> None:
        self.finalize_calls.append(is_error)


# ---------------------------------------------------------------------------
# 场景 1：QQ 完整 reasoning→answer 流程
# ---------------------------------------------------------------------------

class TestQQReasoningThenAnswerFlow:
    """QQ 完整推理→回答流程集成测试"""

    @pytest.fixture
    def controller(self):
        """创建 QQStreamingController 并 mock API"""
        ctrl = QQStreamingController(
            session=AsyncMock(),
            token="test_token",
            openid="test_openid",
            msg_id="test_msg_id",
        )
        return ctrl

    @pytest.fixture
    async def streaming_controller(self, controller):
        """返回已启动流式会话的控制器"""
        with patch("illusion_forge.channels.qq.streaming.send_c2c_stream_message") as mock_send:
            mock_send.return_value = {"id": "stream-123"}
            await controller.start()
            yield controller, mock_send

    @pytest.mark.asyncio
    async def test_reasoning_phase_accumulates_and_displays(self, streaming_controller):
        """发送推理分片 → 验证 is_reasoning_phase=True 且推理文本累积"""
        controller, mock_send = streaming_controller

        await controller.on_reasoning("思考中...")
        await controller.on_reasoning("继续思考")

        assert controller.is_reasoning_phase is True
        assert controller.reasoning_text == "思考中...继续思考"
        display = controller._build_display_text()
        thinking_header = _t("streaming_thinking")
        assert thinking_header in display
        assert "思考中..." in display

    @pytest.mark.asyncio
    async def test_answer_phase_resets_reasoning_and_accumulates(self, streaming_controller):
        """发送回答文本 → 验证 is_reasoning_phase=False 且回答文本累积（使用冻结快照）"""
        controller, mock_send = streaming_controller

        await controller.on_reasoning("思考中")
        await controller.on_text("这是回答")

        assert controller.is_reasoning_phase is False
        assert controller.accumulated_text == "这是回答"
        display = controller._build_display_text()
        # text 阶段使用冻结的 reasoning 快照 + text（前缀兼容）
        thinking_header = _t("streaming_thinking")
        assert display == f"{thinking_header}\n\n思考中\n\n---\n\n这是回答"

    @pytest.mark.asyncio
    async def test_complete_transitions_to_completed_phase(self, streaming_controller):
        """完成 → 验证 phase='completed'"""
        controller, mock_send = streaming_controller

        await controller.on_text("回答内容")
        await controller.complete()

        assert controller.phase == "completed"

    @pytest.mark.asyncio
    async def test_full_flow_display_text_during_reasoning(self, streaming_controller):
        """验证推理阶段显示块引用格式，回答阶段保留 reasoning 前缀"""
        controller, mock_send = streaming_controller

        # 推理阶段
        await controller.on_reasoning("分析问题")
        display_during_reasoning = controller._build_display_text()
        thinking_header = _t("streaming_thinking")
        assert thinking_header in display_during_reasoning
        assert "分析问题" in display_during_reasoning

        # 回答阶段（使用冻结快照 + text，前缀兼容）
        await controller.on_text("最终答案")
        display_during_answer = controller._build_display_text()
        assert display_during_answer == f"{thinking_header}\n\n分析问题\n\n---\n\n最终答案"

    @pytest.mark.asyncio
    async def test_full_flow_with_multiple_chunks(self, streaming_controller):
        """完整流程：多个推理分片 + 多个回答分片 + 完成"""
        controller, mock_send = streaming_controller

        # 推理分片
        await controller.on_reasoning("第一步")
        await controller.on_reasoning("第二步")
        assert controller.is_reasoning_phase is True
        assert controller.reasoning_text == "第一步第二步"

        # 回答分片
        await controller.on_text("回答")
        await controller.on_text("继续")
        assert controller.is_reasoning_phase is False
        assert controller.accumulated_text == "回答继续"

        # 完成
        await controller.complete()
        assert controller.phase == "completed"

        # 验证 _do_finalize 被调用（DONE 状态）
        # 最后一次调用 input_state=10 (DONE)
        last_call = mock_send.call_args_list[-1]
        assert last_call.kwargs.get("input_state") == 10

    @pytest.mark.asyncio
    async def test_stream_msg_id_returned_on_first_flush(self, streaming_controller):
        """start() 发送初始分片并返回 stream_msg_id"""
        controller, mock_send = streaming_controller

        assert controller.stream_msg_id == "stream-123"

    @pytest.mark.asyncio
    async def test_stream_msg_id_reused_on_subsequent_flushes(self, streaming_controller):
        """后续 flush 复用 stream_msg_id"""
        controller, mock_send = streaming_controller

        # start() 已经发送了初始内容 (1 call)
        assert mock_send.call_count == 1

        # on_text 在节流窗口内
        await controller.on_text("first")
        await asyncio.sleep(0.6)

        # 所有调用都复用 start() 返回的 stream_msg_id
        last_call = mock_send.call_args_list[-1]
        assert last_call.kwargs.get("stream_msg_id") == "stream-123"


# ---------------------------------------------------------------------------
# 场景 2：QQ 流式启动失败时的 fallback
# ---------------------------------------------------------------------------

class TestQQFallbackWhenStartFails:
    """QQ 流式启动失败 → 降级到静态消息发送"""

    @pytest.fixture
    def controller(self):
        return QQStreamingController(
            session=AsyncMock(),
            token="test_token",
            openid="test_openid",
            msg_id="test_msg_id",
        )

    @pytest.fixture
    async def streaming_controller(self, controller):
        """返回已启动流式会话的控制器"""
        with patch("illusion_forge.channels.qq.streaming.send_c2c_stream_message") as mock_send:
            mock_send.return_value = {"id": "stream-123"}
            await controller.start()
            yield controller, mock_send

    @pytest.mark.asyncio
    async def test_fallback_when_no_id_returned(self, controller):
        """API 返回无 id 字段 → should_fallback_to_static=True"""
        with patch("illusion_forge.channels.qq.streaming.send_c2c_stream_message") as mock_send:
            mock_send.return_value = {}  # 无 id 字段

            # 尝试发送推理 → 首次 flush 失败
            await controller.on_reasoning("思考中")

            # 由于首次 flush 失败，sent_chunk_count 仍为 0
            # complete 后应触发 fallback
            await controller.complete()

            assert controller.phase == "completed"
            assert controller.should_fallback_to_static is True

    @pytest.mark.asyncio
    async def test_fallback_when_api_raises(self, controller):
        """API 抛出异常 → should_fallback_to_static=True"""
        with patch("illusion_forge.channels.qq.streaming.send_c2c_stream_message") as mock_send:
            mock_send.side_effect = RuntimeError("API 错误")

            await controller.on_text("测试")
            await controller.complete()

            # flush 失败，sent_chunk_count = 0
            assert controller.should_fallback_to_static is True

    @pytest.mark.asyncio
    async def test_no_fallback_when_chunks_sent(self, streaming_controller):
        """成功发送 chunk 后 → should_fallback_to_static=False"""
        controller, mock_send = streaming_controller

        await controller.on_text("成功发送")
        await controller.complete()

        assert controller.should_fallback_to_static is False


# ---------------------------------------------------------------------------
# 场景 3：飞书行为无回归
# ---------------------------------------------------------------------------

class TestFeishuUnchangedBehavior:
    """验证飞书控制器行为无回归"""

    @pytest.mark.asyncio
    async def test_feishu_controller_inherits_base(self):
        """飞书控制器继承自 BaseStreamingController"""
        from illusion_forge.channels.feishu.streaming import FeishuStreamingCardController

        ctrl = FeishuStreamingCardController.__new__(FeishuStreamingCardController)
        BaseStreamingController.__init__(ctrl)
        assert isinstance(ctrl, BaseStreamingController)

    @pytest.mark.asyncio
    async def test_feishu_on_reasoning_requires_streaming_phase(self):
        """飞书 on_reasoning 在 non-streaming 阶段应忽略"""
        from illusion_forge.channels.feishu.streaming import FeishuStreamingCardController

        ctrl = FeishuStreamingCardController(client=AsyncMock(), chat_id="test")
        # 未进入 streaming 阶段
        await ctrl.on_reasoning("思考")
        assert ctrl.reasoning_text == ""
        assert ctrl.is_reasoning_phase is False

    @pytest.mark.asyncio
    async def test_feishu_on_text_requires_streaming_phase(self):
        """飞书 on_text 在 non-streaming 阶段应忽略"""
        from illusion_forge.channels.feishu.streaming import FeishuStreamingCardController

        ctrl = FeishuStreamingCardController(client=AsyncMock(), chat_id="test")
        await ctrl.on_text("回答")
        assert ctrl.accumulated_text == ""

    @pytest.mark.asyncio
    async def test_feishu_transitions_creating_streaming(self):
        """飞书状态机：idle → creating → streaming"""
        from illusion_forge.channels.feishu.streaming import FeishuStreamingCardController

        ctrl = FeishuStreamingCardController(client=AsyncMock(), chat_id="test")
        assert ctrl.phase == "idle"

        # 模拟 _transition 到 creating
        assert ctrl._transition("creating") is True
        assert ctrl.phase == "creating"

        # 模拟 _transition 到 streaming
        assert ctrl._transition("streaming") is True
        assert ctrl.phase == "streaming"

    @pytest.mark.asyncio
    async def test_feishu_invalid_transition_rejected(self):
        """飞书非法状态转换被拒绝"""
        from illusion_forge.channels.feishu.streaming import FeishuStreamingCardController

        ctrl = FeishuStreamingCardController(client=AsyncMock(), chat_id="test")
        # idle 不能直接到 streaming（必须经过 creating）
        assert ctrl._transition("streaming") is False
        assert ctrl.phase == "idle"


# ---------------------------------------------------------------------------
# 场景 4：基类单元测试仍通过
# ---------------------------------------------------------------------------

class TestBaseClassUnitTestsStillPass:
    """验证基类核心功能未被破坏"""

    @pytest.fixture
    def ctrl(self):
        return ConcreteStreamingController()

    @pytest.fixture
    async def streaming_controller(self, ctrl):
        """返回已启动流式会话的控制器"""
        await ctrl.start()
        yield ctrl

    @pytest.mark.asyncio
    async def test_initial_state(self, ctrl):
        assert ctrl.phase == "idle"
        assert ctrl.accumulated_text == ""
        assert ctrl.reasoning_text == ""
        assert ctrl.is_reasoning_phase is False
        assert ctrl.should_fallback_to_static is False

    @pytest.mark.asyncio
    async def test_reasoning_then_text_flow(self, streaming_controller):
        ctrl = streaming_controller
        await ctrl.on_reasoning("思考")
        assert ctrl.is_reasoning_phase is True
        assert ctrl.reasoning_text == "思考"

        await ctrl.on_text("回答")
        assert ctrl.is_reasoning_phase is False
        assert ctrl.accumulated_text == "回答"

    @pytest.mark.asyncio
    async def test_complete_after_sending(self, streaming_controller):
        ctrl = streaming_controller
        await ctrl.on_text("test")
        await ctrl.complete()
        assert ctrl.phase == "completed"
        assert ctrl.finalize_calls == [False]

    @pytest.mark.asyncio
    async def test_abort_no_finalize(self, ctrl):
        await ctrl.on_text("test")
        await ctrl.abort("error")
        assert ctrl.phase == "aborted"
        assert len(ctrl.finalize_calls) == 0

    @pytest.mark.asyncio
    async def test_fallback_after_complete_no_chunks(self, ctrl):
        await ctrl.complete()
        assert ctrl.should_fallback_to_static is True

    @pytest.mark.asyncio
    async def test_no_fallback_after_sending_chunks(self, streaming_controller):
        ctrl = streaming_controller
        await ctrl.on_text("test")
        await ctrl.complete()
        assert ctrl.should_fallback_to_static is False

    def test_build_display_text_reasoning_phase(self, ctrl):
        ctrl._is_reasoning_phase = True
        ctrl._reasoning_text = "思考中"
        result = ctrl._build_display_text()
        thinking_header = _t("streaming_thinking")
        assert thinking_header in result
        assert "思考中" in result

    def test_build_display_text_generation_phase(self, ctrl):
        """text 阶段使用冻结 reasoning 快照 + text（前缀兼容）"""
        ctrl._accumulated_text = "回答"
        ctrl._is_reasoning_phase = False
        ctrl._reasoning_text = "思考中"
        ctrl._reasoning_snapshot = "思考中"  # 模拟已冻结
        result = ctrl._build_display_text()
        thinking_header = _t("streaming_thinking")
        assert result == f"{thinking_header}\n\n思考中\n\n---\n\n回答"

    @pytest.mark.asyncio
    async def test_empty_reasoning_ignored(self, ctrl):
        await ctrl.on_reasoning("")
        assert ctrl.reasoning_text == ""
        assert len(ctrl.flush_calls) == 0

    @pytest.mark.asyncio
    async def test_empty_text_ignored(self, ctrl):
        await ctrl.on_text("")
        assert ctrl.accumulated_text == ""

    @pytest.mark.asyncio
    async def test_reasoning_after_complete_ignored(self, ctrl):
        await ctrl.complete()
        await ctrl.on_reasoning("late")
        assert ctrl.reasoning_text == ""
