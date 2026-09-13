"""验证 local_bash 后台任务完成后通过 bg_agent_tracker 通知 LLM。

相关变更：runtime.py 的 _on_task_complete 回调新增 local_bash 分支，
bash/powershell 后台命令完成后注入 <task-notification> XML。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from illusion_forge.engine.query import BackgroundAgentTracker
from illusion_forge.tasks.types import TaskRecord
from illusion_forge.ui.runtime import _on_task_complete


@pytest.mark.asyncio
async def test_local_bash_completion_notifies_tracker(tmp_path: Path) -> None:
    """local_bash 后台任务完成时应通过 bg_agent_tracker 通知 LLM。"""
    task_id = "b3k9x2qf"
    record = TaskRecord(
        id=task_id,
        type="local_bash",
        status="completed",
        description="echo hello",
        cwd=str(tmp_path),
        output_file=tmp_path / f"{task_id}.log",
        command="echo hello",
        created_at=time.time(),
        started_at=time.time(),
        ended_at=time.time(),
        return_code=0,
    )

    tracker = BackgroundAgentTracker()
    tracker.register(task_id)

    _on_task_complete(task_id, record, tracker)

    completions = await tracker.wait_for_completion()
    assert len(completions) == 1
    completion = completions[0]
    assert completion.agent_id == task_id
    xml = completion.notification_xml
    assert "<task-notification>" in xml
    assert f"<task-id>{task_id}</task-id>" in xml
    assert "<status>completed</status>" in xml
    assert "echo hello" in xml
    assert "exit code 0" in xml


@pytest.mark.asyncio
async def test_local_bash_failed_includes_nonzero_exit_code(tmp_path: Path) -> None:
    """local_bash 失败时应包含非零退出码。"""
    task_id = "b_failed1"
    record = TaskRecord(
        id=task_id,
        type="local_bash",
        status="failed",
        description="false",
        cwd=str(tmp_path),
        output_file=tmp_path / f"{task_id}.log",
        command="false",
        created_at=time.time(),
        started_at=time.time(),
        ended_at=time.time(),
        return_code=1,
    )

    tracker = BackgroundAgentTracker()
    tracker.register(task_id)

    _on_task_complete(task_id, record, tracker)

    completions = await tracker.wait_for_completion()
    assert len(completions) == 1
    xml = completions[0].notification_xml
    assert "<status>failed</status>" in xml
    assert "exit code 1" in xml
    assert completions[0].agent_id == task_id


@pytest.mark.asyncio
async def test_local_bash_no_return_code_omits_exit_code(tmp_path: Path) -> None:
    """return_code 为 None 时 summary 不应包含 exit code 字段。"""
    task_id = "b_norc1"
    record = TaskRecord(
        id=task_id,
        type="local_bash",
        status="completed",
        description="long running job",
        cwd=str(tmp_path),
        output_file=tmp_path / f"{task_id}.log",
        command="sleep 1",
        created_at=time.time(),
        started_at=time.time(),
        ended_at=time.time(),
        return_code=None,
    )

    tracker = BackgroundAgentTracker()
    tracker.register(task_id)

    _on_task_complete(task_id, record, tracker)

    completions = await tracker.wait_for_completion()
    assert len(completions) == 1
    xml = completions[0].notification_xml
    assert "exit code" not in xml
    assert "long running job" in xml


@pytest.mark.asyncio
async def test_agent_task_still_notified(tmp_path: Path) -> None:
    """agent 类任务（local_agent）完成后仍应通知，确保无回归。"""
    task_id = "ar7m1z0p"
    record = TaskRecord(
        id=task_id,
        type="local_agent",
        status="completed",
        description="agent work",
        cwd=str(tmp_path),
        output_file=tmp_path / f"{task_id}.log",
        metadata={"agent_id": "agent_xyz"},
        created_at=time.time(),
        started_at=time.time(),
        ended_at=time.time(),
    )

    tracker = BackgroundAgentTracker()
    tracker.register("agent_xyz")

    _on_task_complete(task_id, record, tracker)

    completions = await tracker.wait_for_completion()
    assert len(completions) == 1
    # agent_id 来自 task.metadata["agent_id"]，与 task_id 不同
    assert completions[0].agent_id == "agent_xyz"
    xml = completions[0].notification_xml
    assert "<task-id>agent_xyz</task-id>" in xml
    assert "agent work" in xml


def test_unrelated_task_type_is_ignored(tmp_path: Path) -> None:
    """其他任务类型（如 in_process_agent）不应触发通知。"""
    task_id = "inproc_1"
    record = TaskRecord(
        id=task_id,
        type="in_process_agent",
        status="completed",
        description="in-proc",
        cwd=str(tmp_path),
        output_file=tmp_path / f"{task_id}.log",
        created_at=time.time(),
    )

    tracker = BackgroundAgentTracker()
    tracker.register(task_id)

    _on_task_complete(task_id, record, tracker)

    # 没有通知被注入
    assert tracker._completions == []
