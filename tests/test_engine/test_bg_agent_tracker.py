"""BackgroundAgentTracker shutdown + 超时保护测试。"""

from __future__ import annotations

import asyncio

from illusion_forge.engine.query import BackgroundAgentTracker


def test_shutdown_wakes_waiters():
    """shutdown 唤醒所有 wait_for_completion 等待者。"""

    async def run():
        tracker = BackgroundAgentTracker()
        tracker.register("agent_1")
        # 启动一个 wait_for_completion task
        wait_task = asyncio.create_task(tracker.wait_for_completion())
        await asyncio.sleep(0.05)  # 让 wait_task 进入等待
        # shutdown 应唤醒等待者
        tracker.shutdown()
        result = await asyncio.wait_for(wait_task, timeout=1.0)
        # shutdown 后返回当前已收集的 completions（应为空）
        assert result == []

    asyncio.run(run())


def test_wait_for_completion_timeout():
    """wait_for_completion 超时后返回当前 completions。"""

    async def run():
        tracker = BackgroundAgentTracker()
        tracker.register("agent_1")
        # 超时后应返回空列表（无 completion）
        result = await tracker.wait_for_completion(timeout=0.1)
        assert result == []
        # tracker 仍可继续使用
        assert tracker.has_pending()

    asyncio.run(run())


def test_notify_completed_guard_against_negative():
    """重复 notify 不会使 _pending_count 变负。"""

    tracker = BackgroundAgentTracker()
    tracker.register("agent_1")
    # 第一次 notify 正常
    tracker.notify_completed("agent_1", "<notification>1</notification>")
    assert tracker._pending_count == 0
    # 重复 notify 不应使 _pending_count 变负
    tracker.notify_completed("agent_1", "<notification>2</notification>")
    assert tracker._pending_count == 0  # guard 生效
    # completions 仍累积（避免丢失通知）
    assert len(tracker._completions) == 2


def test_shutdown_is_idempotent():
    """shutdown 多次调用安全。"""

    tracker = BackgroundAgentTracker()
    tracker.register("agent_1")
    tracker.shutdown()
    tracker.shutdown()  # 不应抛异常
    assert tracker._shutdown is True


def test_notify_after_shutdown_is_noop():
    """shutdown 后 notify_completed 是 no-op。"""

    tracker = BackgroundAgentTracker()
    tracker.shutdown()
    tracker.notify_completed("agent_1", "<notification>1</notification>")
    # shutdown 后不应累积 completion
    assert len(tracker._completions) == 0


def test_wait_for_completion_after_shutdown_returns_immediately():
    """shutdown 后 wait_for_completion 立即返回。"""

    async def run():
        tracker = BackgroundAgentTracker()
        tracker.shutdown()
        result = await tracker.wait_for_completion(timeout=1.0)
        assert result == []

    asyncio.run(run())


def test_first_completion_wakes_waiter_with_multiple_pending():
    """多后台任务时，第一个完成就应唤醒 wait_for_completion。

    回归测试：原版 3cc12ba 每次 notify 都 set wake_event，重构时误改为
    仅在 _pending_count 归 0 时 set，导致多后台任务场景下第一个完成
    无法唤醒主 agent，主 agent 只能等 30s 超时或所有任务完成。
    """
    tracker = BackgroundAgentTracker()
    tracker.register("agent_1")
    tracker.register("agent_2")
    assert tracker._pending_count == 2

    # 第一个 agent 完成（_pending_count 仍为 1）
    tracker.notify_completed("agent_1", "<notification>1</notification>")
    assert tracker._pending_count == 1
    # wake_event 应被 set（修复后行为）
    assert tracker._wake_event.is_set(), (
        "第一个后台任务完成时应 set wake_event，而非等到全部完成"
    )


# ---------------------------------------------------------------------------
# idle_timeout 活动感知模式测试
# ---------------------------------------------------------------------------


def test_notify_activity_refreshes_last_activity_without_setting_event():
    """notify_activity 刷新 _last_activity 但不 set wake_event。

    设计决策：避免对每个 AssistantTextDelta 都空唤醒主循环（流式文本
    生成期间可能有数千个 delta）。wait_for_completion 通过 wait_for
    超时自动重算 remaining，无需 activity 主动唤醒。
    """
    tracker = BackgroundAgentTracker()
    tracker.register("agent_1")
    tracker._wake_event.clear()
    old_activity = tracker._last_activity

    # 模拟时间前进（直接修改 _last_activity 为过去时间）
    tracker._last_activity = old_activity - 10.0
    tracker.notify_activity("agent_1", "AssistantTextDelta")

    # _last_activity 应被刷新为当前时间
    assert tracker._last_activity > old_activity - 10.0
    # wake_event 不应被 set
    assert not tracker._wake_event.is_set()


def test_idle_timeout_returns_empty_when_no_activity():
    """idle_timeout 模式：无活动超过阈值时返回空列表（agent 仍存活）。"""

    async def run():
        tracker = BackgroundAgentTracker()
        tracker.register("agent_1")
        # 把 _last_activity 设为很久以前，模拟无活动
        tracker._last_activity = float("-inf")
        # idle_timeout=0.05，应很快返回空
        result = await tracker.wait_for_completion(idle_timeout=0.05)
        assert result == []
        # tracker 仍可继续使用，agent 仍存活
        assert tracker.has_pending()

    asyncio.run(run())


def test_idle_timeout_keeps_waiting_with_activity():
    """idle_timeout 模式：持续活动时不返回，直到 completion 到达。"""

    async def run():
        tracker = BackgroundAgentTracker()
        tracker.register("agent_1")

        async def _keep_active():
            """模拟后台 agent 持续产出事件。"""
            for _ in range(10):
                await asyncio.sleep(0.02)
                tracker.notify_activity("agent_1", "tick")

        async def _complete_after():
            """模拟后台 agent 在 0.3s 后完成。"""
            await asyncio.sleep(0.3)
            tracker.notify_completed("agent_1", "<notification>done</notification>")

        active_task = asyncio.create_task(_keep_active())
        complete_task = asyncio.create_task(_complete_after())

        # idle_timeout=0.1，但活动每 0.02s 刷新一次，应等到 completion 才返回
        start = asyncio.get_event_loop().time()
        result = await tracker.wait_for_completion(idle_timeout=0.1)
        elapsed = asyncio.get_event_loop().time() - start

        await active_task
        await complete_task

        # 应返回 completion（而非 idle 超时退出）
        assert len(result) == 1
        assert "done" in result[0].notification_xml
        # 耗时应接近 0.3s（completion 时间），而非 0.1s（idle 超时）
        assert elapsed >= 0.25, f"应在 completion 后返回，而非 idle 超时退出，elapsed={elapsed}"

    asyncio.run(run())


def test_idle_timeout_completion_arrives_during_wait():
    """idle_timeout 模式：wait_for 期间 completion 到达时立即返回。"""

    async def run():
        tracker = BackgroundAgentTracker()
        tracker.register("agent_1")

        async def _complete_after():
            await asyncio.sleep(0.05)
            tracker.notify_completed("agent_1", "<notification>done</notification>")

        complete_task = asyncio.create_task(_complete_after())

        # idle_timeout=1.0（足够长），但 completion 在 0.05s 后到达
        start = asyncio.get_event_loop().time()
        result = await tracker.wait_for_completion(idle_timeout=1.0)
        elapsed = asyncio.get_event_loop().time() - start

        await complete_task

        assert len(result) == 1
        assert elapsed < 0.5, f"completion 到达后应立即返回，elapsed={elapsed}"

    asyncio.run(run())


def test_idle_timeout_shutdown_interrupts_wait():
    """idle_timeout 模式：shutdown 中断等待并返回当前 completions。"""

    async def run():
        tracker = BackgroundAgentTracker()
        tracker.register("agent_1")

        async def _shutdown_after():
            await asyncio.sleep(0.05)
            tracker.shutdown()

        shutdown_task = asyncio.create_task(_shutdown_after())

        result = await tracker.wait_for_completion(idle_timeout=10.0)

        await shutdown_task

        # shutdown 后返回空列表
        assert result == []

    asyncio.run(run())


def test_idle_timeout_race_condition_completion_at_timeout_boundary():
    """idle_timeout 边界 race：wait_for 超时瞬间 completion 到达。

    回归测试：wait_for 抛 TimeoutError 后，except 分支应检查 _completions，
    若有则 drain 返回，避免丢失 completion。
    """

    async def run():
        tracker = BackgroundAgentTracker()
        tracker.register("agent_1")

        # 用非常短的 idle_timeout，并在超时瞬间注入 completion
        async def _inject_completion_at_boundary():
            # 等待与 idle_timeout 几乎相同的时间后注入
            await asyncio.sleep(0.05)
            tracker.notify_completed("agent_1", "<notification>race</notification>")

        inject_task = asyncio.create_task(_inject_completion_at_boundary())

        # idle_timeout=0.05，与注入时间几乎相同
        result = await tracker.wait_for_completion(idle_timeout=0.05)

        await inject_task

        # 不论 race 结果如何，都不应丢失 completion：
        # - 若 completion 先到：result 包含 completion
        # - 若 timeout 先到：except 分支检查 _completions，若已被注入则 drain 返回
        # - 若 timeout 后才注入：result 为空，但 tracker._completions 仍有值
        #   （下次 wait_for_completion 会立即返回）
        assert len(result) == 1 or len(tracker._completions) >= 1, (
            "completion 不应丢失"
        )

    asyncio.run(run())
