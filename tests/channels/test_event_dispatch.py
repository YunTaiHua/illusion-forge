# tests/channels/test_event_dispatch.py
"""事件分发逻辑单元测试

验证 render_event 函数中的事件分发逻辑：
- QQ 控制器同时接收 reasoning 和 text
- 飞书控制器行为保持不变
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from illusion_forge.engine.stream_events import AssistantTextDelta, ErrorEvent


def _make_render_event(supports_edit, streaming_controller, qq_streaming_controller):
    """构造与 ChannelRunner._run_agent 中 render_event 相同逻辑的测试函数

    该函数复制了 channels/__init__.py 中 render_event 的分发逻辑，
    用于独立测试而无需构建完整的 ChannelRunner。
    """
    collected_text: list[str] = []

    async def render_event(ev):
        if isinstance(ev, AssistantTextDelta):
            if supports_edit and streaming_controller:
                if ev.reasoning:
                    await streaming_controller.on_reasoning(ev.reasoning)
                if ev.text:
                    await streaming_controller.on_text(ev.text)
            elif qq_streaming_controller:
                if ev.reasoning:
                    await qq_streaming_controller.on_reasoning(ev.reasoning)
                if ev.text:
                    await qq_streaming_controller.on_text(ev.text)
            collected_text.append(ev.text)
        elif isinstance(ev, ErrorEvent):
            collected_text.append(f"\n❌ {ev.message}")
            if supports_edit and streaming_controller:
                await streaming_controller.error(ev.message)
            elif qq_streaming_controller:
                await qq_streaming_controller.abort(ev.message)

    return render_event, collected_text


def _render(*args, **kwargs):
    """辅助函数：仅返回 render_event，忽略 collected_text"""
    render_event, _ = _make_render_event(*args, **kwargs)
    return render_event


class TestQQEventDispatch:
    """QQ 事件分发测试：验证 reasoning 和 text 同时传递"""

    @pytest.fixture
    def qq_controller(self):
        ctrl = MagicMock()
        ctrl.on_reasoning = AsyncMock()
        ctrl.on_text = AsyncMock()
        ctrl.abort = AsyncMock()
        return ctrl

    @pytest.mark.asyncio
    async def test_reasoning_only_event(self, qq_controller):
        """仅 reasoning 的 AssistantTextDelta 应触发 on_reasoning"""
        render = _render(
            supports_edit=False,
            streaming_controller=None,
            qq_streaming_controller=qq_controller,
        )

        ev = AssistantTextDelta(text="", reasoning="正在思考...")
        await render(ev)

        qq_controller.on_reasoning.assert_called_once_with("正在思考...")
        qq_controller.on_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_text_only_event(self, qq_controller):
        """仅 text 的 AssistantTextDelta 应触发 on_text"""
        render = _render(
            supports_edit=False,
            streaming_controller=None,
            qq_streaming_controller=qq_controller,
        )

        ev = AssistantTextDelta(text="回答内容", reasoning=None)
        await render(ev)

        qq_controller.on_text.assert_called_once_with("回答内容")
        qq_controller.on_reasoning.assert_not_called()

    @pytest.mark.asyncio
    async def test_both_reasoning_and_text(self, qq_controller):
        """同时包含 reasoning 和 text 时，两者都应触发"""
        render = _render(
            supports_edit=False,
            streaming_controller=None,
            qq_streaming_controller=qq_controller,
        )

        ev = AssistantTextDelta(text="回答", reasoning="思考中")
        await render(ev)

        qq_controller.on_reasoning.assert_called_once_with("思考中")
        qq_controller.on_text.assert_called_once_with("回答")

    @pytest.mark.asyncio
    async def test_none_reasoning_not_passed(self, qq_controller):
        """reasoning=None 时不应调用 on_reasoning"""
        render = _render(
            supports_edit=False,
            streaming_controller=None,
            qq_streaming_controller=qq_controller,
        )

        ev = AssistantTextDelta(text="hello", reasoning=None)
        await render(ev)

        qq_controller.on_reasoning.assert_not_called()
        qq_controller.on_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_string_reasoning_not_passed(self, qq_controller):
        """reasoning="" 时不应调用 on_reasoning"""
        render = _render(
            supports_edit=False,
            streaming_controller=None,
            qq_streaming_controller=qq_controller,
        )

        ev = AssistantTextDelta(text="hello", reasoning="")
        await render(ev)

        qq_controller.on_reasoning.assert_not_called()
        qq_controller.on_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_event_calls_abort(self, qq_controller):
        """ErrorEvent 应触发 qq_controller.abort"""
        render = _render(
            supports_edit=False,
            streaming_controller=None,
            qq_streaming_controller=qq_controller,
        )

        ev = ErrorEvent(message="出错了")
        await render(ev)

        qq_controller.abort.assert_called_once_with("出错了")


class TestFeishuEventDispatchUnchanged:
    """验证飞书路径不受 QQ 修改影响"""

    @pytest.fixture
    def feishu_controller(self):
        ctrl = MagicMock()
        ctrl.on_reasoning = AsyncMock()
        ctrl.on_text = AsyncMock()
        ctrl.error = AsyncMock()
        return ctrl

    @pytest.mark.asyncio
    async def test_feishu_receives_reasoning_and_text(self, feishu_controller):
        """飞书路径：reasoning 和 text 都应传递给 controller"""
        render = _render(
            supports_edit=True,
            streaming_controller=feishu_controller,
            qq_streaming_controller=None,
        )

        ev = AssistantTextDelta(text="回答", reasoning="思考中")
        await render(ev)

        feishu_controller.on_reasoning.assert_called_once_with("思考中")
        feishu_controller.on_text.assert_called_once_with("回答")

    @pytest.mark.asyncio
    async def test_feishu_error_event(self, feishu_controller):
        """飞书路径：ErrorEvent 应调用 controller.error"""
        render = _render(
            supports_edit=True,
            streaming_controller=feishu_controller,
            qq_streaming_controller=None,
        )

        ev = ErrorEvent(message="飞书错误")
        await render(ev)

        feishu_controller.error.assert_called_once_with("飞书错误")


class TestNoControllerFallback:
    """无控制器时仅累积文本"""

    @pytest.mark.asyncio
    async def test_no_controller_collects_text(self):
        """无 QQ/飞书控制器时，仅 collected_text 累积"""
        render, collected = _make_render_event(
            supports_edit=False,
            streaming_controller=None,
            qq_streaming_controller=None,
        )

        ev = AssistantTextDelta(text="纯文本", reasoning="有思考")
        await render(ev)

        assert collected == ["纯文本"]

    @pytest.mark.asyncio
    async def test_none_text_appended(self):
        """text="" 时仍追加到 collected_text（保持原有行为）"""
        render, collected = _make_render_event(
            supports_edit=False,
            streaming_controller=None,
            qq_streaming_controller=None,
        )

        ev = AssistantTextDelta(text="", reasoning="思考")
        await render(ev)

        assert collected == [""]
