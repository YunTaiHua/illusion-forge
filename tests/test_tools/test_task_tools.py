"""TaskOutputTool 单元测试。

注：TaskCreateTool/TaskGetTool/TaskListTool/TaskUpdateTool 已删除，
TodoWrite 与后台 task 记录之间不再有同步层。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from illusion_forge.tasks.manager import get_task_manager
from illusion_forge.tools.base import ToolExecutionContext
from illusion_forge.tools.task_output_tool import TaskOutputTool, TaskOutputToolInput


@pytest.mark.asyncio
async def test_task_output_tool_reads_existing_task(tmp_path: Path, monkeypatch):
    """TaskOutputTool 能读取已存在任务的输出。"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = get_task_manager()
    # 直接通过 manager 创建任务，不再依赖 TaskCreateTool
    record = await manager.create_shell_task(
        description="test task",
        cwd=str(tmp_path),
        command="printf 'hello'",
    )
    # 等待任务完成
    await asyncio.wait_for(manager._waiters[record.id], timeout=5)  # type: ignore[attr-defined]

    context = ToolExecutionContext(cwd=tmp_path)
    tool = TaskOutputTool()
    result = await tool.execute(TaskOutputToolInput(task_id=record.id), context)
    assert "hello" in result.output
