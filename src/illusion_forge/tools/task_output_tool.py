"""
任务输出读取工具
================

本模块提供读取后台任务输出的功能。

主要组件：
    - TaskOutputTool: 读取任务输出日志的工具

使用示例：
    >>> from illusion_forge.tools import TaskOutputTool
    >>> tool = TaskOutputTool()
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from illusion_forge.tasks.manager import get_task_manager
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult


class TaskOutputToolInput(BaseModel):
    """任务输出获取参数。

    属性：
        task_id: 要读取输出的任务 ID
        max_bytes: 最大返回字节数
    """

    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(description="The task ID to get output from", alias="taskId")
    max_bytes: int = Field(default=12000, ge=1, le=100000)


class TaskOutputTool(BaseTool[TaskOutputToolInput]):
    """读取后台任务的输出。

    用于查看后台任务的输出日志。支持读取以下类型的后台任务输出：
    - bash/powershell 后台命令：返回 stdout/stderr 累积内容
    - 进程内后台 agent：优先返回 agent 的最终结果文本，无结果时返回 output_file 内容
    - 子进程 agent 任务：返回 output_file 内容
    """

    name = "task_output"
    description = """- Retrieves output from a running or completed task (background shell, agent, or remote session)
- Takes a task_id parameter identifying the task
- Returns the task output along with status information
- Works with all task types: background shells, async agents, and remote sessions

task_id source:
- Background bash/powershell command: returned by the bash/powershell tool as "task_id=bXXXXXX"
- Background agent: returned by the agent tool as "task_id=aXXXXXX"
- Do NOT use the OS pid — always use the task_id from the tool's return value"""
    input_model = TaskOutputToolInput

    def is_read_only(self, arguments: TaskOutputToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: TaskOutputToolInput, context: ToolExecutionContext) -> ToolResult:
        del context
        try:
            output = get_task_manager().read_task_output(arguments.task_id, max_bytes=arguments.max_bytes)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=output or "(no output)")
