"""
发送消息工具
============

本模块提供向运行中的代理发送消息的功能。

主要组件：
    - SendMessageTool: 向代理发送消息的工具

使用示例：
    >>> from illusion_forge.tools import SendMessageTool
    >>> tool = SendMessageTool()
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult
from illusion_forge.utils.aioqueue import QueueShutDown

logger = logging.getLogger(__name__)


class SendMessageToolInput(BaseModel):
    """发送消息参数。

    属性：
        to: 目标代理名称或 ID
        message: 消息内容
    """

    to: str = Field(description="Agent name or ID to send the message to")
    message: str = Field(description="Message content to send")


class SendMessageTool(BaseTool[SendMessageToolInput]):
    """向运行中的代理发送消息。

    用于与代理通信或发送继续指令。
    """

    name = "send_message"
    description = """Send a message to another agent.

Use this tool to communicate with running agents. Messages from teammates are delivered automatically; you don't check an inbox. Refer to teammates by name, never by UUID.

Usage:
- Send to agent by name: `SendMessage({ to: "researcher", message: "..." })`
- Send to agent by ID: `SendMessage({ to: "agent_abc123", message: "..." })`

When continuing a completed agent, the agent resumes with its full context preserved.
"""
    input_model = SendMessageToolInput

    async def execute(self, arguments: SendMessageToolInput, context: ToolExecutionContext) -> ToolResult:
        """执行发送消息。

        Args:
            arguments: 工具输入参数。
            context: 工具执行上下文。

        Returns:
            ToolResult: 工具执行结果。
        """
        # 延迟导入以避免循环依赖
        from illusion_forge.swarm.agent_executor import (
            TeammateMessage,
            get_active_agent,
            get_active_agent_by_name,
        )
        from illusion_forge.tasks.manager import get_task_manager

        target = arguments.to
        message_text = arguments.message

        # 首先尝试通过名称查找活跃的进程内代理
        agent_ctx = get_active_agent_by_name(target)
        if agent_ctx is None:
            agent_ctx = get_active_agent(target)

        if agent_ctx is not None:
            msg = TeammateMessage(
                text=message_text,
                from_agent="coordinator",
            )
            try:
                await agent_ctx.message_queue.put(msg)
            except QueueShutDown:
                pass  # agent 已关闭，丢弃消息
            logger.debug("[SendMessage] Sent message to in-process agent %s", agent_ctx.agent_id)
            return ToolResult(output=f"Sent message to agent '{target}'")

        # 尝试通过任务管理器写入（子进程代理）
        try:
            await get_task_manager().write_to_task(target, message_text)
            return ToolResult(output=f"Sent message to task '{target}'")
        except ValueError:
            pass

        # 尝试查找匹配的任务
        task_manager = get_task_manager()
        for task in task_manager.list_tasks(status="running"):
            if task.description and target in task.description:
                try:
                    await task_manager.write_to_task(task.id, message_text)
                    return ToolResult(output=f"Sent message to task '{task.id}' (matched '{target}')")
                except ValueError as exc:
                    return ToolResult(output=str(exc), is_error=True)

        return ToolResult(
            output=f"No active agent or task found matching '{target}'",
            is_error=True,
        )
