"""agent_executor 取消模型测试。"""

from __future__ import annotations

import asyncio

from illusion_forge.swarm.agent_executor import AgentAbortController, AgentExecutionContext
from illusion_forge.utils.aioqueue import Queue


def test_cancel_event_triggers_shutdown():
    """cancel_event 触发后 message_queue 被 shutdown，consumer 退出。"""

    async def run():
        ctx = AgentExecutionContext(
            agent_id="test",
            agent_name="test",
            message_queue=Queue(),
        )
        messages: list = []
        consumer_task = asyncio.create_task(_message_consumer(messages, ctx))

        # 模拟 run_agent_in_process 的 cancel watcher：cancel_event 触发后 shutdown
        async def _cancel_watcher():
            await ctx.abort_controller.cancel_event.wait()
            ctx.message_queue.shutdown()

        watcher_task = asyncio.create_task(_cancel_watcher())
        await asyncio.sleep(0.05)  # 让 consumer 进入 await get()

        # 触发取消
        ctx.abort_controller.request_cancel(reason="test")

        # consumer 应在 watcher shutdown 后退出
        await asyncio.wait_for(consumer_task, timeout=2.0)
        await watcher_task
        assert messages == []

    from illusion_forge.swarm.agent_executor import _message_consumer

    asyncio.run(run())


def test_timeout_triggers_force_cancel():
    """request_cancel(force=True) 同时设置 force_cancel 和 cancel_event。"""
    controller = AgentAbortController()
    assert not controller.is_cancelled
    controller.request_cancel(reason="timeout", force=True)
    assert controller.force_cancel.is_set()
    assert controller.cancel_event.is_set()
    assert controller.is_cancelled
    assert controller.reason == "timeout"


def test_message_queue_shutdown_wakes_consumer():
    """message_queue.shutdown() 唤醒 await get() 的 consumer。"""

    async def run():
        ctx = AgentExecutionContext(
            agent_id="test",
            agent_name="test",
            message_queue=Queue(),
        )
        messages = []
        consumer_task = asyncio.create_task(_message_consumer(messages, ctx))
        await asyncio.sleep(0.05)  # 让 consumer 进入 await get()
        ctx.message_queue.shutdown()
        await consumer_task  # 应立即完成
        assert messages == []

    from illusion_forge.swarm.agent_executor import _message_consumer

    asyncio.run(run())
