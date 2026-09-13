"""
后台任务管理器模块
=================

本模块管理后台 shell 和 agent 子进程任务。

主要功能：
    - 创建待处理任务
    - 创建 Shell 任务
    - 创建 Agent 任务
    - 更新任务
    - 停止任务
    - 读写任务输出

类说明：
    - BackgroundTaskManager: 后台任务管理器类
    - create_pending_task: 创建待处理任务
    - create_shell_task: 创建 Shell 任务
    - create_agent_task: 创建 Agent 任务
    - update_task: 更新任务
    - stop_task: 停止任务

使用示例：
    >>> from illusion_forge.tasks.manager import BackgroundTaskManager, get_task_manager
    >>> # 获取任务管理器
    >>> manager = get_task_manager()
    >>> # 创建 Shell 任务
    >>> record = await manager.create_shell_task(command="ls -la", description="列出文件", cwd=".")
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shlex
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from illusion_forge.config.paths import get_tasks_dir
from illusion_forge.tasks.types import TaskRecord, TaskStatus, TaskType, to_task_internal_status
from illusion_forge.utils.log_cleanup import cleanup_old_files
from illusion_forge.utils.shell import create_shell_subprocess, terminate_process_tree

logger = logging.getLogger(__name__)

_TASK_LOG_TTL_DAYS = 7  # task log 保留天数

# === 任务归属会话上下文 ===
#
# Web 多会话模式下，每个会话的行处理任务在独立 asyncio.Task 中运行。
# 后台任务（agent / bash / powershell 等）由行任务内的工具调用创建，
# asyncio 的 contextvars 会随 create_task / 协程调用自动传播，
# 因此在任务创建处 stamp 归属会话 ID 到 metadata["owner_session_id"]，
# 供后台任务完成通知按归属路由到对应会话引擎的 bg_agent_tracker
# （避免全局单回调把完成通知投递到错误的会话）。
# terminal 端不设置此上下文，stamp 值为空字符串，不影响现有逻辑。
session_owner_ctx: ContextVar[str | None] = ContextVar(
    "illusion_task_session_owner", default=None
)


def current_task_session_owner() -> str | None:
    """返回当前异步上下文归属的会话 ID。

    Returns:
        str | None: 会话 ID；None 表示无归属（如 terminal 端 / 后台任务）
    """
    return session_owner_ctx.get()


class BackgroundTaskManager:
    """管理 shell 和 agent 子进程任务。"""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._waiters: dict[str, asyncio.Task[None]] = {}
        self._output_locks: dict[str, asyncio.Lock] = {}
        self._input_locks: dict[str, asyncio.Lock] = {}
        self._generations: dict[str, int] = {}
        # 子进程退出时回调，用于通知 bg_agent_tracker（由 runtime.py 注册）
        self.on_task_complete: Callable[[str, TaskRecord], None] | None = None
        # 清理超过 TTL 的旧 task log
        self._cleanup_old_task_logs()

    def _cleanup_old_task_logs(self) -> None:
        """清理超过 TTL 的 task log 文件（统一走 log_cleanup 工具）。"""
        cleanup_old_files(get_tasks_dir(), "*.log", max_age_days=_TASK_LOG_TTL_DAYS)

    def create_pending_task(
        self,
        *,
        subject: str,
        description: str,
        active_form: str | None = None,
    ) -> TaskRecord:
        """创建用于跟踪的待处理任务（非后台进程）。"""
        task_id = _task_id("in_process_teammate")
        output_path = get_tasks_dir() / f"{task_id}.log"
        record = TaskRecord(
            id=task_id,
            type="in_process_teammate",
            status="pending",
            description=description,
            subject=subject,
            active_form=active_form,
            cwd=str(Path.cwd().resolve()),
            output_file=output_path,
            created_at=time.time(),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        self._stamp_owner_session(record)
        self._tasks[task_id] = record
        return record

    async def create_shell_task(
        self,
        *,
        command: str,
        description: str,
        cwd: str | Path,
        task_type: TaskType = "local_bash",
    ) -> TaskRecord:
        """启动后台 shell 命令。"""
        task_id = _task_id(task_type)
        output_path = get_tasks_dir() / f"{task_id}.log"
        record = TaskRecord(
            id=task_id,
            type=task_type,
            status="running",
            description=description,
            cwd=str(Path(cwd).resolve()),
            output_file=output_path,
            command=command,
            created_at=time.time(),
            started_at=time.time(),
        )
        output_path.write_text("", encoding="utf-8")
        self._stamp_owner_session(record)
        self._tasks[task_id] = record
        self._output_locks[task_id] = asyncio.Lock()
        self._input_locks[task_id] = asyncio.Lock()
        await self._start_process(task_id)
        return record

    async def create_agent_task(
        self,
        *,
        prompt: str,
        description: str,
        cwd: str | Path,
        task_type: TaskType = "local_agent",
        model: str | None = None,
        api_key: str | None = None,
        command: str | None = None,
    ) -> TaskRecord:
        """作为子进程启动本地 agent 任务。"""
        if command is None:
            # 子进程会自行 load_settings，无需注入 api_key 到命令行
            cmd = ["python", "-m", "illusion_forge", "--headless"]
            if model:
                cmd.extend(["--model", model])
            command = " ".join(shlex.quote(part) for part in cmd)

        record = await self.create_shell_task(
            command=command,
            description=description,
            cwd=cwd,
            task_type=task_type,
        )
        updated = replace(record, prompt=prompt)
        if task_type != "local_agent":
            updated.metadata["agent_mode"] = task_type
        self._tasks[record.id] = updated
        await self.write_to_task(record.id, prompt)
        return updated

    def register_in_process_agent_task(
        self,
        *,
        description: str,
        cwd: str | Path,
        prompt: str | None = None,
        async_task: asyncio.Task[None] | None = None,
    ) -> TaskRecord:
        """注册进程内后台 agent 任务。

        与 create_shell_task 不同，本方法不启动子进程，而是绑定一个已有的
        asyncio.Task（由调用方创建并传入）。task_stop 通过 task.cancel() 终止，
        task_output 读取 output_file（调用方通过 write_to_task_output 累积）。
        采用 LocalAgentTaskState + abortController 模式。
        """
        task_id = _task_id("in_process_agent")
        output_path = get_tasks_dir() / f"{task_id}.log"
        record = TaskRecord(
            id=task_id,
            type="in_process_agent",
            status="running",
            description=description,
            cwd=str(Path(cwd).resolve()),
            output_file=output_path,
            prompt=prompt,
            created_at=time.time(),
            started_at=time.time(),
            async_task=async_task,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        self._stamp_owner_session(record)
        self._tasks[task_id] = record
        self._output_locks[task_id] = asyncio.Lock()
        return record

    def _stamp_owner_session(self, record: TaskRecord) -> None:
        """stamp 任务归属会话 ID 到 metadata。

        从当前异步上下文读取归属会话（Web 多会话模式下由行任务设置），
        terminal 端上下文为空时跳过，保持原行为。

        Args:
            record: 任务记录
        """
        owner = session_owner_ctx.get()
        if owner:
            record.metadata["owner_session_id"] = owner

    async def write_to_task_output(self, task_id: str, data: str) -> None:
        """向任务输出文件追加数据（用于进程内 agent 输出累积）。

        与 write_to_task 不同，本方法不写入 stdin，而是把 data 追加到
        output_file，供 task_output 读取。
        """
        task = self._require_task(task_id)
        async with self._output_locks[task_id]:
            with task.output_file.open("ab") as handle:
                handle.write(data.encode("utf-8"))

    def set_task_result(self, task_id: str, result: str) -> None:
        """设置进程内 agent 的最终结果文本。

        任务完成后调用，task_output 会优先返回 result。
        local_agent 优先读取内存 result.content 的行为）。
        """
        task = self._require_task(task_id)
        task.result = result

    def complete_in_process_agent(
        self,
        task_id: str,
        *,
        success: bool,
        result: str | None = None,
    ) -> TaskRecord:
        """标记进程内 agent 任务完成。

        由 _run_background 协程在退出时调用，更新状态、记录 result、
        触发 on_task_complete 回调。
        """
        task = self._require_task(task_id)
        task.status = "completed" if success else "failed"
        task.ended_at = time.time()
        if result is not None:
            task.result = result
        task.async_task = None

        # 通知 on_task_complete 回调（若已注册）
        if self.on_task_complete is not None:
            try:
                self.on_task_complete(task_id, task)
            except Exception:
                logger.exception("[manager] on_task_complete callback failed for %s", task_id)
        return task

    def get_task(self, task_id: str) -> TaskRecord | None:
        """返回一个任务记录。"""
        return self._tasks.get(task_id)

    def list_tasks(self, *, status: TaskStatus | None = None) -> list[TaskRecord]:
        """返回所有任务，可选按状态过滤。"""
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        return sorted(tasks, key=lambda item: item.created_at, reverse=True)

    def update_task(
        self,
        task_id: str,
        *,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        status: str | None = None,
        owner: str | None = None,
        progress: int | None = None,
        status_note: str | None = None,
        metadata: dict[str, Any] | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
        comments: str | None = None,
    ) -> TaskRecord:
        """更新用于协调和 UI 显示的可变任务元数据。"""
        task = self._require_task(task_id)

        # 处理删除
        if status == "deleted":
            self._tasks.pop(task_id, None)
            return task

        if subject is not None:
            task.subject = subject
        if description is not None and description.strip():
            task.description = description.strip()
        if active_form is not None:
            task.active_form = active_form
        if status is not None:
            task.status = to_task_internal_status(status)
        if owner is not None:
            task.owner = owner
        if progress is not None:
            task.metadata["progress"] = str(progress)
        if status_note is not None:
            note = status_note.strip()
            if note:
                task.metadata["status_note"] = note
            else:
                task.metadata.pop("status_note", None)
        if metadata is not None:
            for key, value in metadata.items():
                if value is None:
                    task.metadata.pop(key, None)
                else:
                    task.metadata[key] = str(value)
        if add_blocks is not None:
            for block_id in add_blocks:
                if block_id not in task.blocks:
                    task.blocks.append(block_id)
        if add_blocked_by is not None:
            for blocker_id in add_blocked_by:
                if blocker_id not in task.blocked_by:
                    task.blocked_by.append(blocker_id)
        if comments is not None:
            task.comments.append(comments)
        return task

    async def stop_task(self, task_id: str) -> TaskRecord:
        """终止运行中的任务。

        支持两类任务：
        - 子进程任务（local_bash / local_agent / remote_agent）：terminate -> kill
        - 进程内异步任务（in_process_agent）：asyncio.Task.cancel()

        对已自然结束的任务（completed/failed/killed）直接返回当前状态，
        不抛异常，让调用方根据 task.status 区分"已停止"和"已结束"。
        """
        task = self._require_task(task_id)

        # 已结束的任务直接返回（保留原有状态，让工具提示"already finished"）
        if task.status in {"completed", "failed", "killed"}:
            return task

        # 进程内异步任务：通过 asyncio.Task.cancel() 终止
        if task.type == "in_process_agent":
            async_task = task.async_task
            if async_task is not None and not async_task.done():
                async_task.cancel()
                try:
                    await asyncio.wait_for(async_task, timeout=3)
                except (TimeoutError, asyncio.CancelledError) as exc:
                    logger.debug("清理异步任务失败: %s", exc)
            task.async_task = None
            task.status = "killed"
            task.ended_at = time.time()
            # 通知 on_task_complete 回调
            if self.on_task_complete is not None:
                try:
                    self.on_task_complete(task_id, task)
                except Exception:
                    logger.exception("[manager] on_task_complete callback failed for %s", task_id)
            return task

        # 子进程任务：终止整个进程树（terminate -> kill）
        # 仅 terminate shell 父进程无法终止其派生的子进程（如 bash 内的
        # python/powershell），必须按平台杀进程树：
        #   - Windows: taskkill /T /F（遍历父进程 ID 树）
        #   - POSIX: killpg（后台任务以独立进程组启动）
        process = self._processes.get(task_id)
        if process is None:
            # 进程已不在 _processes 中，可能已自然结束但 watcher 还没更新状态。
            # 直接返回当前 task，让工具提示"already finished"而非报错。
            return task

        # 先标记 killed：watcher/_background_wait 完成时看到 killed 不会
        # 覆盖为 completed/failed，保证 on_task_complete 能识别"用户停止"
        task.status = "killed"
        task.ended_at = time.time()

        await terminate_process_tree(process)

        # cancel watcher（manager 的 _watch_process / 工具的 _background_wait）：
        # 进程被 taskkill 强杀后，Windows 上 process.wait()/stdout.read() 可能
        # 长时间不返回（ProactorEventLoop 句柄机制），不 cancel 会导致等待超时
        # 拖慢 stop。cancel 后协程走 CancelledError 分支完成清理。
        waiter = self._waiters.get(task_id)
        if waiter is not None and not waiter.done():
            waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(waiter, timeout=3)

        # 清理注册（watcher 的 CancelledError 分支不负责 pop）
        self._processes.pop(task_id, None)
        self._waiters.pop(task_id, None)
        return task

    async def write_to_task(self, task_id: str, data: str) -> None:
        """向任务 stdin 写入一行，需要时自动恢复本地 agent。"""
        task = self._require_task(task_id)
        async with self._input_locks[task_id]:
            process = await self._ensure_writable_process(task)
            assert process.stdin is not None
            process.stdin.write((data.rstrip("\n") + "\n").encode("utf-8"))
            try:
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                if task.type not in {"local_agent", "remote_agent", "in_process_teammate"}:
                    raise ValueError(f"Task {task_id} does not accept input") from None
                process = await self._restart_agent_task(task)
                assert process.stdin is not None
                process.stdin.write((data.rstrip("\n") + "\n").encode("utf-8"))
                await process.stdin.drain()

    def read_task_output(self, task_id: str, *, max_bytes: int = 12000) -> str:
        """返回任务输出。

        获取任务输出数据：
        - 进程内 agent（in_process_agent）：优先返回内存 result，无 result 时回退到 output_file
        - 子进程任务（local_bash / local_agent / remote_agent）：返回 output_file 尾部
        """
        task = self._require_task(task_id)

        # 进程内 agent 优先返回内存 result（最终 assistant 文本）
        if task.type == "in_process_agent" and task.result:
            return task.result

        content = task.output_file.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_bytes:
            return content[-max_bytes:]
        return content

    async def _watch_process(
        self,
        task_id: str,
        process: asyncio.subprocess.Process,
        generation: int,
    ) -> None:
        """监视子进程直到完成。"""
        reader = asyncio.create_task(self._copy_output(task_id, process))
        try:
            return_code = await process.wait()
        except asyncio.CancelledError:
            # 取消时终止整个进程树，避免孤儿进程
            await terminate_process_tree(process)
            reader.cancel()
            with contextlib.suppress(Exception):
                await reader
            # 清理注册 + 关闭 transport（stop_task 取消 watcher 时调用）
            self._processes.pop(task_id, None)
            self._waiters.pop(task_id, None)
            transport = getattr(process, "_transport", None)
            if transport is not None:
                with contextlib.suppress(Exception):
                    transport.close()
            raise
        await reader

        current_generation = self._generations.get(task_id)
        if current_generation != generation:
            return

        task = self._tasks[task_id]
        task.return_code = return_code
        if task.status != "killed":
            task.status = "completed" if return_code == 0 else "failed"
        task.ended_at = time.time()
        self._processes.pop(task_id, None)
        self._waiters.pop(task_id, None)

        # 通知 on_task_complete 回调（若已注册）
        if self.on_task_complete is not None:
            try:
                self.on_task_complete(task_id, task)
            except Exception:
                logger.exception("[manager] on_task_complete callback failed for %s", task_id)

    async def _copy_output(self, task_id: str, process: asyncio.subprocess.Process) -> None:
        """将进程输出复制到任务输出文件。"""
        if process.stdout is None:
            return
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                return
            async with self._output_locks[task_id]:
                with self._tasks[task_id].output_file.open("ab") as handle:
                    handle.write(chunk)

    def _require_task(self, task_id: str) -> TaskRecord:
        """返回任务记录，不存在则抛出异常。"""
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"No task found with ID: {task_id}")
        return task

    async def _start_process(self, task_id: str) -> asyncio.subprocess.Process:
        """启动任务进程。"""
        task = self._require_task(task_id)
        if task.command is None:
            raise ValueError(f"Task {task_id} does not have a command to run")

        generation = self._generations.get(task_id, 0) + 1
        self._generations[task_id] = generation
        process = await create_shell_subprocess(
            task.command,
            cwd=task.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            new_process_group=True,
        )
        self._processes[task_id] = process
        self._waiters[task_id] = asyncio.create_task(
            self._watch_process(task_id, process, generation)
        )
        return process

    async def _ensure_writable_process(
        self,
        task: TaskRecord,
    ) -> asyncio.subprocess.Process:
        """确保任务可写入，必要时重启。"""
        process = self._processes.get(task.id)
        if process is not None and process.stdin is not None and process.returncode is None:
            return process
        if task.type not in {"local_agent", "remote_agent", "in_process_teammate"}:
            raise ValueError(f"Task {task.id} does not accept input")
        return await self._restart_agent_task(task)

    async def _restart_agent_task(self, task: TaskRecord) -> asyncio.subprocess.Process:
        """重启 agent 任务。"""
        if task.command is None:
            raise ValueError(f"Task {task.id} does not have a restart command")

        waiter = self._waiters.get(task.id)
        if waiter is not None and not waiter.done():
            await waiter

        restart_count = int(task.metadata.get("restart_count", "0")) + 1
        task.metadata["restart_count"] = str(restart_count)
        task.status = "running"
        task.started_at = time.time()
        task.ended_at = None
        task.return_code = None
        return await self._start_process(task.id)


# 按任务目录隔离的任务管理器缓存
_MANAGERS_BY_KEY: dict[str, BackgroundTaskManager] = {}


def get_task_manager() -> BackgroundTaskManager:
    """返回单例任务管理器。"""
    current_key = str(get_tasks_dir().resolve())
    manager = _MANAGERS_BY_KEY.get(current_key)
    if manager is None:
        manager = BackgroundTaskManager()
        _MANAGERS_BY_KEY[current_key] = manager
    return manager


def _task_id(task_type: TaskType) -> str:
    """生成任务 ID 前缀。
    - local_bash -> b{8 hex}   (如 b3k9x2qf)
    - local_agent / in_process_agent -> a{8 hex}  (如 ar7m1z0p)
    - remote_agent -> r{8 hex}
    - in_process_teammate -> t{8 hex}
    """
    prefixes = {
        "local_bash": "b",
        "local_agent": "a",
        "remote_agent": "r",
        "in_process_teammate": "t",
        "in_process_agent": "a", 
    }
    return f"{prefixes[task_type]}{uuid4().hex[:8]}"
