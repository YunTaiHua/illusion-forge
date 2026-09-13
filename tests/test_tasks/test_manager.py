"""Tests for background task management."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from illusion_forge.tasks.manager import BackgroundTaskManager, get_task_manager


@pytest.mark.asyncio
async def test_create_shell_task_and_read_output(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="printf 'hello task'",
        description="hello",
        cwd=tmp_path,
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "completed"
    assert "hello task" in manager.read_task_output(task.id)


@pytest.mark.asyncio
async def test_create_agent_task_with_command_override_and_write(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="first",
        description="agent",
        cwd=tmp_path,
        command="while read line; do echo \"got:$line\"; break; done",
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    assert "got:first" in manager.read_task_output(task.id)


@pytest.mark.asyncio
async def test_write_to_stopped_agent_task_restarts_process(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="ready",
        description="agent",
        cwd=tmp_path,
        command="while read line; do echo \"got:$line\"; break; done",
    )
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    await manager.write_to_task(task.id, "follow-up")
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    output = manager.read_task_output(task.id)
    assert "got:ready" in output
    assert "got:follow-up" in output
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.metadata["restart_count"] == "1"


@pytest.mark.asyncio
async def test_stop_task(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="sleep 30",
        description="sleeper",
        cwd=tmp_path,
    )
    await manager.stop_task(task.id)
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "killed"


@pytest.mark.asyncio
async def test_stop_already_completed_task_returns_without_error(tmp_path: Path, monkeypatch):
    """对已自然结束的任务调用 stop_task 应直接返回，不抛 'not running' 异常。"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    record = await manager.create_shell_task(
        command="exit 0",
        description="quick exit",
        cwd=tmp_path,
    )
    # 等待任务自然完成
    await asyncio.wait_for(manager._waiters[record.id], timeout=5)

    # 再次调用 stop_task 不应抛异常
    result = await manager.stop_task(record.id)
    assert result.status == "completed"  # 保留原状态，不是 killed


@pytest.mark.asyncio
async def test_stop_in_process_agent_already_completed(tmp_path: Path, monkeypatch):
    """对已完成的进程内 agent 调用 stop_task 应直接返回，不抛异常。"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    record = manager.register_in_process_agent_task(
        description="already done agent",
        cwd=tmp_path,
    )
    manager.complete_in_process_agent(record.id, success=True, result="done")

    # 再次调用 stop_task 不应抛异常
    result = await manager.stop_task(record.id)
    assert result.status == "completed"


def test_get_task_manager_keeps_managers_per_task_list(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ILLUSION_TASK_LIST_ID", raising=False)

    default_manager = get_task_manager()
    default_task = default_manager.create_pending_task(
        subject="default",
        description="default task",
    )

    monkeypatch.setenv("ILLUSION_TASK_LIST_ID", "team-alpha")
    team_manager = get_task_manager()
    assert team_manager is not default_manager
    assert team_manager.get_task(default_task.id) is None

    monkeypatch.delenv("ILLUSION_TASK_LIST_ID", raising=False)
    restored_default_manager = get_task_manager()
    assert restored_default_manager is default_manager
    assert restored_default_manager.get_task(default_task.id) is not None


@pytest.mark.asyncio
async def test_on_task_complete_callback_invoked_on_process_exit(tmp_path, monkeypatch):
    """子进程退出时 on_task_complete 回调应被调用，传入正确的 task_id 和最终 task 记录。"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()
    completed_calls: list[tuple[str, str, str]] = []  # (task_id, status, type)

    def _on_complete(task_id: str, task):
        completed_calls.append((task_id, task.status, task.type))

    manager.on_task_complete = _on_complete

    record = await manager.create_shell_task(
        description="callback test",
        cwd=str(tmp_path),
        command="exit 0",
    )
    # 等待 watcher 完成
    import asyncio
    await asyncio.wait_for(manager._waiters[record.id], timeout=5)  # type: ignore[attr-defined]

    assert len(completed_calls) == 1
    assert completed_calls[0][0] == record.id
    assert completed_calls[0][1] == "completed"
    assert completed_calls[0][2] == "local_bash"


@pytest.mark.asyncio
async def test_on_task_complete_none_does_not_crash(tmp_path, monkeypatch):
    """on_task_complete 为 None 时不应崩溃。"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()
    # on_task_complete 默认 None
    assert manager.on_task_complete is None

    record = await manager.create_shell_task(
        description="no callback test",
        cwd=str(tmp_path),
        command="printf 'ok'",
    )
    import asyncio
    await asyncio.wait_for(manager._waiters[record.id], timeout=5)  # type: ignore[attr-defined]
    # 不崩溃即通过
    task = manager.get_task(record.id)
    assert task is not None


@pytest.mark.asyncio
async def test_register_in_process_agent_task(tmp_path: Path, monkeypatch):
    """进程内 agent 任务注册：返回 a 前缀 task_id，状态 running，类型 in_process_agent。"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    async def _dummy_bg() -> None:
        await asyncio.sleep(0.1)

    bg_task = asyncio.create_task(_dummy_bg())
    record = manager.register_in_process_agent_task(
        description="in-process agent",
        cwd=tmp_path,
        prompt="test prompt",
        async_task=bg_task,
    )

    assert record.id.startswith("a")
    assert record.type == "in_process_agent"
    assert record.status == "running"
    assert record.prompt == "test prompt"
    assert record.async_task is bg_task
    assert manager.get_task(record.id) is record

    await bg_task


@pytest.mark.asyncio
async def test_stop_in_process_agent_cancels_async_task(tmp_path: Path, monkeypatch):
    """task_stop 对 in_process_agent 类型应通过 asyncio.Task.cancel() 终止。"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    cancelled = asyncio.Event()

    async def _long_running() -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    bg_task = asyncio.create_task(_long_running())
    record = manager.register_in_process_agent_task(
        description="cancellable agent",
        cwd=tmp_path,
        async_task=bg_task,
    )
    # 让出控制权，使后台任务有机会启动并到达 sleep 挂起点
    await asyncio.sleep(0.1)

    await manager.stop_task(record.id)
    assert cancelled.is_set(), "asyncio.Task should have been cancelled"
    assert record.status == "killed"
    assert record.async_task is None


@pytest.mark.asyncio
async def test_read_task_output_prefers_result_for_in_process_agent(tmp_path: Path, monkeypatch):
    """read_task_output 对 in_process_agent 应优先返回内存 result。"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    record = manager.register_in_process_agent_task(
        description="agent with result",
        cwd=tmp_path,
    )
    # 先写入 output_file
    await manager.write_to_task_output(record.id, "intermediate log\n")
    # 设置最终结果
    manager.set_task_result(record.id, "final agent answer")

    output = manager.read_task_output(record.id)
    assert output == "final agent answer", "应优先返回 result 而非 output_file"


@pytest.mark.asyncio
async def test_complete_in_process_agent_triggers_callback(tmp_path: Path, monkeypatch):
    """complete_in_process_agent 应更新状态并触发 on_task_complete 回调。"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()
    completed_calls: list[tuple[str, str]] = []

    def _on_complete(task_id: str, task):
        completed_calls.append((task_id, task.status))

    manager.on_task_complete = _on_complete

    record = manager.register_in_process_agent_task(
        description="callback test",
        cwd=tmp_path,
    )
    manager.complete_in_process_agent(record.id, success=True, result="done")

    assert record.status == "completed"
    assert record.result == "done"
    assert record.async_task is None
    assert len(completed_calls) == 1
    assert completed_calls[0] == (record.id, "completed")


def test_cleanup_old_task_logs_removes_expired(monkeypatch, tmp_path):
    """超过 7 天的 task log 应在初始化时被清理"""
    import os
    import time
    from pathlib import Path

    data_dir = tmp_path / "data"
    tasks_dir = data_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(data_dir))

    # 创建一个 8 天前的旧 log
    old_log = tasks_dir / "bold_log.log"
    old_log.write_text("old content")
    old_time = time.time() - 8 * 24 * 3600  # 8 天前
    os.utime(old_log, (old_time, old_time))

    # 创建一个近期的 log
    recent_log = tasks_dir / "bnew_log.log"
    recent_log.write_text("recent content")

    from illusion_forge.tasks.manager import BackgroundTaskManager
    BackgroundTaskManager()

    assert not old_log.exists(), "旧 log 应被清理"
    assert recent_log.exists(), "近期 log 应保留"


def test_cleanup_old_task_logs_keeps_recent(monkeypatch, tmp_path):
    """7 天内的 task log 应保留"""
    data_dir = tmp_path / "data"
    tasks_dir = data_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(data_dir))

    log = tasks_dir / "brecent.log"
    log.write_text("content")

    from illusion_forge.tasks.manager import BackgroundTaskManager
    BackgroundTaskManager()

    assert log.exists()
