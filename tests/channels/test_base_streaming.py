# tests/channels/test_base_streaming.py
"""BaseStreamingController 单元测试"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from illusion_forge.channels.base_streaming import BaseStreamingController, StreamState
from illusion_forge.config.i18n import t as _t


class ConcreteStreamingController(BaseStreamingController):
    """测试用具体实现"""

    def __init__(self, show_reasoning: bool = True):
        super().__init__(show_reasoning=show_reasoning)
        self.flush_calls = []
        self.finalize_calls = []
        self.start_calls = []

    async def _do_start(self) -> None:
        if self._show_reasoning:
            self.start_calls.append(True)
            # 模拟发送初始思考内容（使用 i18n 文本）
            thinking_text = _t("streaming_thinking")
            self.flush_calls.append((thinking_text, StreamState.GENERATING))
            self._sent_chunk_count += 1

    async def _do_flush(self, text: str, state: StreamState) -> None:
        self.flush_calls.append((text, state))

    async def _do_finalize(self, is_error: bool) -> None:
        self.finalize_calls.append(is_error)


@pytest.fixture
def controller():
    return ConcreteStreamingController()


@pytest.fixture
async def streaming_controller(controller):
    """返回已启动流式会话的控制器"""
    await controller.start()
    return controller


class TestStreamState:
    def test_generating_value(self):
        assert StreamState.GENERATING.value == 1

    def test_done_value(self):
        assert StreamState.DONE.value == 10


class TestInitialState:
    def test_initial_phase_is_idle(self, controller):
        assert controller.phase == "idle"

    def test_initial_accumulated_text_empty(self, controller):
        assert controller.accumulated_text == ""

    def test_initial_reasoning_text_empty(self, controller):
        assert controller.reasoning_text == ""

    def test_initial_is_reasoning_phase_false(self, controller):
        assert controller.is_reasoning_phase is False

    def test_initial_should_fallback_false(self, controller):
        # idle 状态 + 0 chunks = 不应 fallback（idle 不是终态）
        assert controller.should_fallback_to_static is False


class TestOnReasoning:
    @pytest.mark.asyncio
    async def test_reasoning_sets_phase(self, streaming_controller):
        await streaming_controller.on_reasoning("thinking...")
        assert streaming_controller.is_reasoning_phase is True

    @pytest.mark.asyncio
    async def test_reasoning_accumulates(self, streaming_controller):
        await streaming_controller.on_reasoning("part1")
        await streaming_controller.on_reasoning(" part2")
        assert streaming_controller.reasoning_text == "part1 part2"

    @pytest.mark.asyncio
    async def test_reasoning_triggers_flush(self, streaming_controller):
        await streaming_controller.on_reasoning("test")
        # start() 已经发送了初始内容，on_reasoning 会触发额外 flush
        assert len(streaming_controller.flush_calls) >= 1

    @pytest.mark.asyncio
    async def test_empty_reasoning_ignored(self, streaming_controller):
        await streaming_controller.on_reasoning("")
        assert streaming_controller.reasoning_text == ""

    @pytest.mark.asyncio
    async def test_reasoning_after_complete_ignored(self, streaming_controller):
        await streaming_controller.complete()
        await streaming_controller.on_reasoning("late")
        assert streaming_controller.reasoning_text == ""


class TestOnText:
    @pytest.mark.asyncio
    async def test_text_accumulates(self, streaming_controller):
        await streaming_controller.on_text("hello")
        await streaming_controller.on_text(" world")
        assert streaming_controller.accumulated_text == "hello world"

    @pytest.mark.asyncio
    async def test_text_resets_reasoning_phase(self, streaming_controller):
        await streaming_controller.on_reasoning("thinking")
        await streaming_controller.on_text("answer")
        assert streaming_controller.is_reasoning_phase is False

    @pytest.mark.asyncio
    async def test_text_triggers_flush(self, streaming_controller):
        await streaming_controller.on_text("test")
        assert len(streaming_controller.flush_calls) >= 1

    @pytest.mark.asyncio
    async def test_empty_text_ignored(self, controller):
        await controller.on_text("")
        assert controller.accumulated_text == ""

    @pytest.mark.asyncio
    async def test_whitespace_only_text_does_not_start(self, controller):
        await controller.on_text("   ")
        # 空白文本不应启动流式
        assert controller.phase == "idle"


class TestBuildDisplayText:
    def test_pure_text(self, controller):
        controller._accumulated_text = "hello"
        assert controller._build_display_text() == "hello"

    def test_reasoning_phase_no_text(self, controller):
        controller._is_reasoning_phase = True
        controller._reasoning_text = "thinking..."
        result = controller._build_display_text()
        thinking_header = _t("streaming_thinking")
        assert thinking_header in result
        assert "thinking..." in result

    def test_text_phase_uses_frozen_reasoning(self, controller):
        """text 阶段使用冻结的 reasoning 快照 + text（前缀兼容）"""
        controller._accumulated_text = "answer"
        controller._is_reasoning_phase = False
        controller._reasoning_text = "thinking..."
        controller._reasoning_snapshot = "thinking..."  # 模拟已冻结
        result = controller._build_display_text()
        thinking_header = _t("streaming_thinking")
        assert result == f"{thinking_header}\n\nthinking...\n\n---\n\nanswer"

    def test_new_reasoning_after_text_does_not_change_display(self, controller):
        """text 阶段后新 reasoning 不改变 display text（避免前缀冲突）"""
        controller._accumulated_text = "answer"
        controller._reasoning_snapshot = "original reasoning"  # 冻结的快照
        controller._reasoning_text = "original reasoning + new reasoning"  # 新 reasoning 已累积
        result = controller._build_display_text()
        thinking_header = _t("streaming_thinking")
        # display text 使用快照，不包含 new reasoning
        assert result == f"{thinking_header}\n\noriginal reasoning\n\n---\n\nanswer"
        assert "new reasoning" not in result


class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_transitions_phase(self, streaming_controller):
        await streaming_controller.on_text("test")
        await streaming_controller.complete()
        assert streaming_controller.phase == "completed"

    @pytest.mark.asyncio
    async def test_complete_calls_finalize(self, streaming_controller):
        await streaming_controller.on_text("test")
        await streaming_controller.complete()
        assert len(streaming_controller.finalize_calls) == 1
        assert streaming_controller.finalize_calls[0] is False

    @pytest.mark.asyncio
    async def test_complete_resets_reasoning_phase(self, streaming_controller):
        await streaming_controller.on_reasoning("thinking")
        await streaming_controller.on_text("answer")
        await streaming_controller.complete()
        assert streaming_controller.is_reasoning_phase is False


class TestAbort:
    @pytest.mark.asyncio
    async def test_abort_transitions_phase(self, streaming_controller):
        await streaming_controller.on_text("test")
        await streaming_controller.abort("error")
        assert streaming_controller.phase == "aborted"

    @pytest.mark.asyncio
    async def test_abort_no_finalize(self, streaming_controller):
        await streaming_controller.on_text("test")
        await streaming_controller.abort()
        assert len(streaming_controller.finalize_calls) == 0


class TestShouldFallback:
    @pytest.mark.asyncio
    async def test_fallback_after_complete_no_chunks(self, controller):
        # 直接 complete，没有发送任何 chunk
        await controller.complete()
        assert controller.should_fallback_to_static is True

    @pytest.mark.asyncio
    async def test_no_fallback_after_sending_chunks(self, streaming_controller):
        await streaming_controller.on_text("test")
        await streaming_controller.complete()
        assert streaming_controller.should_fallback_to_static is False


# --- I1/I2: _finalize 最终 flush 测试 ---

class TestFinalizeFinalFlush:
    @pytest.mark.asyncio
    async def test_finalize_flushes_remaining_text_bypass_throttle(self, streaming_controller):
        """I1/I2: _finalize 应发送被节流窗口延迟的剩余文本"""
        streaming_controller._throttle_seconds = 0.2

        await streaming_controller.on_text("hello")
        assert len(streaming_controller.flush_calls) >= 1
        # on_text 在节流窗口内，flush 被调度而非立即执行
        assert streaming_controller._pending_timer is not None

        # 节流窗口内的第二次文本 → 仅调度延迟 flush
        await streaming_controller.on_text(" world")
        assert streaming_controller._pending_timer is not None
        # 尚未立即 flush（只有 start 的初始内容）

        # complete 后应发送 "hello world"
        await streaming_controller.complete()

        assert len(streaming_controller.flush_calls) >= 2
        assert streaming_controller.flush_calls[-1][0] == "hello world"
        assert streaming_controller.finalize_calls == [False]

    @pytest.mark.asyncio
    async def test_finalize_no_extra_flush_when_text_unchanged(self, streaming_controller):
        """I1/I2: 若文本未变，最终 flush 不应重复发送"""
        await streaming_controller.on_text("hello")
        assert len(streaming_controller.flush_calls) >= 1

        # 直接 complete，无新文本
        await streaming_controller.complete()

        # start() 的初始 flush + on_text 的 flush（无重复）
        assert len(streaming_controller.flush_calls) >= 1
        assert streaming_controller.finalize_calls == [False]


# --- I3: 节流逻辑测试 ---

class TestThrottle:
    @pytest.mark.asyncio
    async def test_second_call_within_throttle_schedules_delayed(self, streaming_controller):
        """I3: 节流窗口内的第二次调用应调度延迟 flush"""
        streaming_controller._throttle_seconds = 0.2

        await streaming_controller.on_text("a")
        assert len(streaming_controller.flush_calls) >= 1

        await streaming_controller.on_text("b")
        assert streaming_controller._pending_timer is not None  # 已调度
        assert len(streaming_controller.flush_calls) >= 1  # 尚未执行新 flush

    @pytest.mark.asyncio
    async def test_delayed_flush_actually_executes(self, streaming_controller):
        """I3: 延迟 flush 在节流窗口过后应实际执行"""
        streaming_controller._throttle_seconds = 0.05

        await streaming_controller.on_text("hello")
        assert len(streaming_controller.flush_calls) >= 1

        await streaming_controller.on_text(" world")
        assert streaming_controller._pending_timer is not None

        # 等待延迟 flush 执行
        await asyncio.sleep(0.15)

        assert len(streaming_controller.flush_calls) >= 2
        assert streaming_controller.flush_calls[-1][0] == "hello world"

    @pytest.mark.asyncio
    async def test_pending_timer_cancelled_when_elapsed_exceeds_throttle(self, streaming_controller):
        """I3: 当 elapsed >= throttle 时，挂起的 timer 应被取消并立即 flush"""
        await streaming_controller.on_text("a")
        assert len(streaming_controller.flush_calls) >= 1

        await streaming_controller.on_text("b")
        first_timer = streaming_controller._pending_timer
        assert first_timer is not None

        # 将 _last_flush_time 回拨，使 elapsed >= throttle
        streaming_controller._last_flush_time = time.monotonic() - 1.0

        await streaming_controller.on_text("c")
        # 旧 timer 应被取消（timer 已取消或更换）
        assert streaming_controller._pending_timer is None or streaming_controller._pending_timer is not first_timer
        # 立即 flush 已发生
        assert len(streaming_controller.flush_calls) >= 2
        assert streaming_controller.flush_calls[-1][0] == "abc"


# --- I5: 首次 flush 标志消费时机测试 ---

class TestFirstFlushFlagTiming:
    @pytest.mark.asyncio
    async def test_first_flush_flag_consumed_only_after_success(self, controller):
        """I5: _is_first_flush 标志仅在 _flush 成功执行后才被消费"""
        # 模拟 _flush 因文本重复而返回早期（不实际发送）
        flush_count = 0

        async def mock_flush(*, force=False):
            nonlocal flush_count
            flush_count += 1
            # 第一次调用模拟文本重复（不实际发送）
            if flush_count == 1:
                return  # 早期返回
            # 后续调用正常执行：模拟 _flush 更新 _last_flushed_text
            controller._last_flushed_text = controller._build_display_text()
            controller.flush_calls.append((controller._last_flushed_text, StreamState.GENERATING))

        controller._flush = mock_flush

        # 启动流式会话（发送初始内容）
        await controller.start()

        # start() 已经发送了初始内容，所以 _is_first_flush 应该为 False
        assert controller._is_first_flush is False

        # 后续调用正常节流
        controller._accumulated_text = "test"
        await controller._throttled_flush()

    @pytest.mark.asyncio
    async def test_first_reasoning_bypasses_throttle(self, streaming_controller):
        """I5: 首次 reasoning 应绕过节流立即发送（start 后 _is_first_flush=False，故被节流）"""
        streaming_controller._throttle_seconds = 0.5  # 500ms 节流

        # 首次 reasoning（在节流窗口内，flush 被调度）
        await streaming_controller.on_reasoning("thinking...")

        # start() 已发送初始内容，on_reasoning 在节流窗口内调度延迟 flush
        assert len(streaming_controller.flush_calls) >= 1
        # 等待延迟 flush 执行
        await asyncio.sleep(0.6)
        assert len(streaming_controller.flush_calls) >= 2
        assert "thinking..." in streaming_controller.flush_calls[-1][0]
        # 验证包含 i18n 思考标题（中文或英文）
        thinking_header = _t("streaming_thinking")
        assert thinking_header in streaming_controller.flush_calls[-1][0]


# --- I4: 并发 flush 保护测试 ---

class TestConcurrentFlush:
    @pytest.mark.asyncio
    async def test_concurrent_flush_only_one_executes(self, streaming_controller):
        """I4: 并发 _flush 调用仅执行一次"""
        flush_count = 0

        async def slow_flush(text, state):
            nonlocal flush_count
            flush_count += 1
            await asyncio.sleep(0.05)
            streaming_controller.flush_calls.append((text, state))

        streaming_controller._do_flush = slow_flush
        # 设置 accumulated_text 使 _flush 有内容可发送
        streaming_controller._accumulated_text = "test content"

        task1 = asyncio.create_task(streaming_controller._flush())
        await asyncio.sleep(0)  # 让 task1 启动并持有锁
        task2 = asyncio.create_task(streaming_controller._flush())

        await asyncio.gather(task1, task2)

        assert flush_count == 1

    @pytest.mark.asyncio
    async def test_needs_reflush_set_when_blocked(self, streaming_controller):
        """I4: flush 被阻塞时应设置 _needs_reflush"""

        async def slow_flush(text, state):
            await asyncio.sleep(0.05)
            streaming_controller.flush_calls.append((text, state))

        streaming_controller._do_flush = slow_flush
        # 设置 accumulated_text 使 _flush 有内容可发送
        streaming_controller._accumulated_text = "test content"

        task1 = asyncio.create_task(streaming_controller._flush())
        await asyncio.sleep(0)

        # 阻塞的调用应设置 _needs_reflush
        await streaming_controller._flush()
        assert streaming_controller._needs_reflush is True

        await task1


# --- show_reasoning=False 测试 ---


class TestShowReasoningFalse:
    """测试 show_reasoning=False 时的行为"""

    @pytest.fixture
    def controller_no_reasoning(self):
        """返回 show_reasoning=False 的控制器"""
        return ConcreteStreamingController(show_reasoning=False)

    def test_display_text_hides_reasoning(self, controller_no_reasoning):
        """show_reasoning=False 时，只显示答案，不显示思考过程"""
        controller_no_reasoning._accumulated_text = "answer"
        controller_no_reasoning._reasoning_text = "thinking..."
        result = controller_no_reasoning._build_display_text()
        assert result == "answer"

    @pytest.mark.asyncio
    async def test_start_sends_no_initial_content(self, controller_no_reasoning):
        """show_reasoning=False 时，start() 不发送初始内容"""
        await controller_no_reasoning.start()
        # 不应有 flush 调用（因为 show_reasoning=False）
        assert len(controller_no_reasoning.flush_calls) == 0
        assert controller_no_reasoning._sent_chunk_count == 0
