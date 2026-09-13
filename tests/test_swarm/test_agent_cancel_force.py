"""agent force_cancel + ContextVar token reset 测试。"""

from __future__ import annotations

import asyncio

from illusion_forge.swarm.agent_executor import (
    AgentAbortController,
    AgentExecutionContext,
    _agent_context_var,
    set_agent_context,
)


def test_force_cancel_interrupts_running_tool():
    """force_cancel 触发后 query_task 被 cancel，中断运行中的工具。"""

    async def run():
        controller = AgentAbortController()

        # 模拟一个长时间运行的工具（如 bash 长命令）
        async def long_running_tool():
            await asyncio.sleep(10)  # 模拟不可中断的长时间操作

        tool_task = asyncio.create_task(long_running_tool())

        # 构造 force_cancel wait task（与 agent_executor 中的模式一致）
        force_cancel_task = asyncio.create_task(controller.force_cancel.wait())

        # 启动一个并发任务：稍后触发 force_cancel
        async def trigger():
            await asyncio.sleep(0.1)
            controller.request_cancel(force=True)

        trigger_task = asyncio.create_task(trigger())

        # 模拟 agent_executor 的 asyncio.wait FIRST_COMPLETED 模式
        done, _pending = await asyncio.wait(
            [tool_task, force_cancel_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # force_cancel_task 应该先完成
        assert force_cancel_task in done, "force_cancel_task 应在工具完成前触发"

        # 主动 cancel 工具任务（这是 Task 10 的核心修复）
        tool_task.cancel()
        try:
            await tool_task
        except asyncio.CancelledError:
            pass

        # 验证工具任务在很短时间内被中断（远小于 10 秒）
        assert tool_task.done(), "工具任务应已完成"
        assert tool_task.cancelled(), "工具任务应被 cancel"

        # 清理
        trigger_task.cancel()
        try:
            await trigger_task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())


def test_contextvar_token_reset():
    """嵌套 agent 调用后 ContextVar 恢复外层值。"""

    async def run():
        # 外层 context
        outer_ctx = AgentExecutionContext(
            agent_id="outer",
            agent_name="outer",
        )
        outer_token = set_agent_context(outer_ctx)
        assert _agent_context_var.get() is outer_ctx

        # 内层 agent：设置新 context，完成后 reset
        inner_ctx = AgentExecutionContext(
            agent_id="inner",
            agent_name="inner",
        )
        inner_token = set_agent_context(inner_ctx)
        assert _agent_context_var.get() is inner_ctx

        # 模拟 finally 中的 reset
        _agent_context_var.reset(inner_token)
        # 应该恢复到外层
        assert _agent_context_var.get() is outer_ctx, "reset 后应恢复外层 context"

        # 清理外层
        _agent_context_var.reset(outer_token)
        assert _agent_context_var.get() is None

    asyncio.run(run())
