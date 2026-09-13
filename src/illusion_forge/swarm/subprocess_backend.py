"""
子进程代理执行后端模块
=====================

本模块实现基于子进程的 TeammateExecutor 接口。
使用现有的 :class:`~illusion_forge.tasks.manager.BackgroundTaskManager`
来创建和管理子进程，通过 stdin/stdout 进行通信。

主要组件：
    - SubprocessBackend: 子进程执行后端

使用示例：
    >>> from illusion_forge.swarm.subprocess_backend import SubprocessBackend
    >>> backend = SubprocessBackend()
    >>> result = await backend.spawn(config)
"""

from __future__ import annotations

import json
import logging

from illusion_forge.swarm.agent_executor import (
    _build_agent_cli_flags,
    _get_agent_command,
)
from illusion_forge.swarm.types import (
    BackendType,
    SpawnResult,
    TeammateMessage,
    TeammateSpawnConfig,
)
from illusion_forge.tasks.manager import get_task_manager

logger = logging.getLogger(__name__)


class SubprocessBackend:
    """TeammateExecutor 实现，每个代理作为独立子进程运行。"""

    type: BackendType = "subprocess"

    def __init__(self) -> None:
        self._agent_tasks: dict[str, str] = {}

    def is_available(self) -> bool:
        """子进程后端始终可用。"""
        return True

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult:
        """通过任务管理器作为子进程生成新代理。"""
        agent_id = f"{config.name}@{config.team}"

        # 构建 CLI 命令
        flags = _build_agent_cli_flags(
            model=config.model,
            permission_mode=None,
        )

        agent_cmd = _get_agent_command()
        cmd_parts = [agent_cmd, "-m", "illusion_forge"] + flags
        command = " ".join(cmd_parts)

        # 创建任务
        manager = get_task_manager()
        try:
            record = await manager.create_agent_task(
                prompt=config.prompt,
                description=f"Agent: {agent_id}",
                cwd=config.cwd,
                task_type="in_process_teammate",
                model=config.model,
                command=command,
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            logger.error("[SubprocessBackend] Failed to spawn agent %s: %s", agent_id, exc)
            return SpawnResult(
                task_id="",
                agent_id=agent_id,
                backend_type=self.type,
                success=False,
                error=str(exc),
            )

        self._agent_tasks[agent_id] = record.id
        logger.debug("[SubprocessBackend] Spawned agent %s as task %s", agent_id, record.id)
        return SpawnResult(
            task_id=record.id,
            agent_id=agent_id,
            backend_type=self.type,
        )

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None:
        """通过 stdin 向运行中的代理发送消息。"""
        task_id = self._agent_tasks.get(agent_id)
        if task_id is None:
            raise ValueError(f"No active subprocess for agent {agent_id!r}")

        payload = {
            "text": message.text,
            "from": message.from_agent,
            "timestamp": message.timestamp,
        }
        if message.color:
            payload["color"] = message.color
        if message.summary:
            payload["summary"] = message.summary

        manager = get_task_manager()
        await manager.write_to_task(task_id, json.dumps(payload))
        logger.debug("[SubprocessBackend] Sent message to %s (task %s)", agent_id, task_id)

    async def shutdown(self, agent_id: str, *, force: bool = False) -> bool:
        """终止子进程代理。"""
        task_id = self._agent_tasks.get(agent_id)
        if task_id is None:
            logger.warning("[SubprocessBackend] shutdown() called for unknown agent %s", agent_id)
            return False

        manager = get_task_manager()
        try:
            await manager.stop_task(task_id)
        except ValueError as exc:
            logger.debug("[SubprocessBackend] stop_task for %s: %s", task_id, exc)
        finally:
            self._agent_tasks.pop(agent_id, None)

        logger.debug("[SubprocessBackend] Shut down agent %s (task %s)", agent_id, task_id)
        return True

    def get_task_id(self, agent_id: str) -> str | None:
        """返回给定代理的任务管理器任务 ID。"""
        return self._agent_tasks.get(agent_id)
