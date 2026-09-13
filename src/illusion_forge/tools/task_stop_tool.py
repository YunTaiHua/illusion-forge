"""
任务停止工具
============

本模块提供停止正在运行的后台任务的功能。

主要组件：
    - TaskStopTool: 停止后台任务的工具

使用示例：
    >>> from illusion_forge.tools import TaskStopTool
    >>> tool = TaskStopTool()
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from illusion_forge.tasks.manager import get_task_manager
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult


class TaskStopToolInput(BaseModel):
    """任务停止参数。

    属性：
        task_id: 要停止的后台任务 ID
    """

    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(description="The ID of the background task to stop", alias="taskId")


class TaskStopTool(BaseTool[TaskStopToolInput]):
    """停止后台任务。

    用于终止长时间运行的任务。支持停止以下类型的后台任务：
    - bash/powershell 后台命令（task_id 来自工具返回值，形如 b3k9x2qf）
    - 进程内后台 agent（task_id 来自 agent 工具返回值，形如 a3f2c1b4）
    - 子进程 agent 任务（task_id 来自 agent 工具返回值）
    """

    name = "task_stop"
    description = """- Stops a running background task by its ID
- Takes a task_id parameter identifying the task to stop
- Returns a success or failure status
- Use this tool when you need to terminate a long-running task

task_id source:
- Background bash/powershell command: returned by the bash/powershell tool as "task_id=bXXXXXX"
- Background agent: returned by the agent tool as "task_id=aXXXXXX"
- Do NOT use the OS pid — always use the task_id from the tool's return value"""
    input_model = TaskStopToolInput

    async def execute(self, arguments: TaskStopToolInput, context: ToolExecutionContext) -> ToolResult:
        del context
        manager = get_task_manager()
        try:
            task = await manager.stop_task(arguments.task_id)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)

        # 根据 task 的最终状态返回友好的提示信息
        # - killed: 本次 task_stop 终止的
        # - completed/failed: 任务在调用 task_stop 之前已自然结束
        if task.status == "killed":
            return ToolResult(output=f"Stopped task {task.id}")
        # 任务已自然结束
        return_code_info = f" (return_code={task.return_code})" if task.return_code is not None else ""
        return ToolResult(
            output=(
                f"Task {task.id} already finished with status '{task.status}'{return_code_info}. "
                f"No stop needed — use task_output to read its result."
            ),
        )
