"""
进程内代理执行后端模块
=====================

本模块实现进程内的代理执行后端。
使用 :mod:`contextvars` 在当前 Python 进程中将代理作为 asyncio Task 运行，
实现每个代理的上下文隔离。

主要组件：
    - InProcessBackend: 进程内执行后端，实现 TeammateExecutor 协议

使用示例：
    >>> from illusion_forge.swarm.in_process import InProcessBackend
    >>> backend = InProcessBackend()
    >>> result = await backend.spawn(config)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field

from illusion_forge.swarm.agent_executor import (
    AgentAbortController,
    AgentExecutionContext,
    AgentSpawnConfig,
    _register_agent,
    _unregister_agent,
    set_agent_context,
)
from illusion_forge.swarm.types import (
    BackendType,
    SpawnResult,
    TeammateMessage,
    TeammateSpawnConfig,
)
from illusion_forge.utils.aioqueue import QueueShutDown

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# InProcessBackend
# ---------------------------------------------------------------------------


@dataclass
class _AgentEntry:
    """运行中进程内代理的内部注册表条目。"""

    task: asyncio.Task[None]
    abort_controller: AgentAbortController
    task_id: str
    started_at: float = field(default_factory=time.time)


class InProcessBackend:
    """将代理作为当前进程中的 asyncio Task 运行的 TeammateExecutor。"""

    type: BackendType = "in_process"

    def __init__(self) -> None:
        self._active: dict[str, _AgentEntry] = {}

    def is_available(self) -> bool:
        """进程内后端始终可用。"""
        return True

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult:
        """将进程内代理生成为 asyncio Task。"""
        agent_id = f"{config.name}@{config.team}"
        task_id = f"in_process_{uuid.uuid4().hex[:12]}"

        # 检查是否已存在活跃的同名代理
        if agent_id in self._active:
            entry = self._active[agent_id]
            if not entry.task.done():
                logger.warning("[InProcessBackend] spawn(): %s is already running", agent_id)
                return SpawnResult(
                    task_id=task_id,
                    agent_id=agent_id,
                    backend_type=self.type,
                    success=False,
                    error=f"Agent {agent_id!r} is already running",
                )

        # 创建中止控制器
        abort_controller = AgentAbortController()

        # 创建代理生成配置
        spawn_config = AgentSpawnConfig(
            name=config.name,
            prompt=config.prompt,
            cwd=config.cwd,
            model=config.model,
            system_prompt=config.system_prompt,
            permission_mode=None,
            parent_session_id=config.parent_session_id,
        )

        # 预先创建并注册执行上下文，以便 send_message 可以立即找到代理
        from illusion_forge.swarm.agent_executor import AgentExecutionContext, _register_agent
        ctx = AgentExecutionContext(
            agent_id=agent_id,
            agent_name=config.name,
            prompt=config.prompt,
            model=config.model,
            cwd=__import__("pathlib").Path(config.cwd),
            abort_controller=abort_controller,
        )
        _register_agent(ctx)

        # 将 TeammateSpawnConfig 的 query_context / parent_registry 存入 ctx
        # 供 _run_agent 调用 run_agent_in_process 使用
        ctx.query_context = config.query_context
        ctx.parent_registry = config.parent_registry

        # 创建 asyncio Task
        task = asyncio.create_task(
            self._run_agent(spawn_config, agent_id, abort_controller, ctx),
            name=f"agent-{agent_id}",
        )

        entry = _AgentEntry(
            task=task,
            abort_controller=abort_controller,
            task_id=task_id,
        )
        self._active[agent_id] = entry

        # 添加完成回调
        def _on_done(t: asyncio.Task[None]) -> None:
            self._active.pop(agent_id, None)
            if not t.cancelled() and t.exception() is not None:
                logger.error("[InProcessBackend] Agent %s raised exception: %s", agent_id, t.exception())

        task.add_done_callback(_on_done)

        logger.debug("[InProcessBackend] spawned %s (task_id=%s)", agent_id, task_id)
        return SpawnResult(
            task_id=task_id,
            agent_id=agent_id,
            backend_type=self.type,
        )

    async def _run_agent(
        self,
        config: AgentSpawnConfig,
        agent_id: str,
        abort_controller: AgentAbortController,
        ctx: AgentExecutionContext | None = None,
    ) -> None:
        """运行代理的内部协程。

        当 ctx 提供 query_context 和 parent_registry 时，调用 run_agent_in_process
        执行实际代理逻辑；否则回退到 stub 行为（等待取消）。
        """
        if ctx is None:
            ctx = AgentExecutionContext(
                agent_id=agent_id,
                agent_name=config.name,
                prompt=config.prompt,
                model=config.model,
                cwd=__import__("pathlib").Path(config.cwd),
                abort_controller=abort_controller,
            )
            _register_agent(ctx)
        set_agent_context(ctx)

        # 从 ctx 读取 TeammateSpawnConfig 传递的上下文
        query_context = getattr(ctx, "query_context", None)
        parent_registry = getattr(ctx, "parent_registry", None)

        try:
            if query_context is not None and parent_registry is not None:
                from illusion_forge.swarm.agent_executor import run_agent_in_process
                logger.info("[InProcessBackend] %s: agent started (in-process)", agent_id)
                ctx.status = "running"
                await run_agent_in_process(
                    config=config,
                    query_context=query_context,
                    parent_registry=parent_registry,
                    is_async=True,
                    existing_context=ctx,
                )
            else:
                # 回退到 stub 行为（未提供 query_context）
                logger.warning(
                    "[InProcessBackend] %s: no query_context, running stub", agent_id
                )
                ctx.status = "running"
                # 等待取消信号（force=True 也会设置 cancel_event，故只需等这一个）
                await abort_controller.cancel_event.wait()

        except asyncio.CancelledError:
            logger.debug("[InProcessBackend] %s: task cancelled", agent_id)
            raise
        except Exception:
            logger.exception("[InProcessBackend] %s: unhandled exception", agent_id)
        finally:
            ctx.status = "stopped"
            _unregister_agent(agent_id)

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None:
        """向运行中的代理发送消息。"""
        # 首先检查 self._active 中是否有该代理
        entry = self._active.get(agent_id)
        if entry is not None and not entry.task.done():
            # 代理正在运行，但需要找到其 AgentExecutionContext
            # 从全局注册表中查找
            from illusion_forge.swarm.agent_executor import get_active_agent
            agent_ctx = get_active_agent(agent_id)
            if agent_ctx is not None:
                try:
                    await agent_ctx.message_queue.put(message)  # type: ignore[arg-type]
                except QueueShutDown:
                    pass  # agent 已关闭，丢弃消息
                logger.debug("[InProcessBackend] sent message to %s", agent_id)
                return

        # 回退：尝试从全局注册表查找
        from illusion_forge.swarm.agent_executor import get_active_agent, get_active_agent_by_name
        agent_name = agent_id.split("@")[0] if "@" in agent_id else agent_id

        agent_ctx = get_active_agent(agent_id)
        if agent_ctx is None:
            agent_ctx = get_active_agent_by_name(agent_name)

        if agent_ctx is not None:
            try:
                await agent_ctx.message_queue.put(message)  # type: ignore[arg-type]
            except QueueShutDown:
                pass  # agent 已关闭，丢弃消息
            logger.debug("[InProcessBackend] sent message to %s", agent_id)
        else:
            raise ValueError(f"No active agent found for {agent_id!r}")

    async def shutdown(self, agent_id: str, *, force: bool = False, timeout: float = 10.0) -> bool:
        """终止运行中的进程内代理。"""
        entry = self._active.get(agent_id)
        if entry is None:
            logger.debug("[InProcessBackend] shutdown(): %s not found", agent_id)
            return False

        if entry.task.done():
            self._active.pop(agent_id, None)
            return True

        if force:
            entry.abort_controller.request_cancel(reason="force shutdown", force=True)
            entry.task.cancel()
            # 直接 await task（无 shield），超时则放弃等待（task 已 cancel，最终会退出）
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(entry.task, timeout=timeout)
        else:
            entry.abort_controller.request_cancel(reason="graceful shutdown")
            try:
                # 直接 await task（无 shield），允许取消信号传播
                await asyncio.wait_for(entry.task, timeout=timeout)
            except TimeoutError:
                logger.warning("[InProcessBackend] %s did not exit within %.1fs — forcing", agent_id, timeout)
                entry.abort_controller.request_cancel(reason="timeout — forcing", force=True)
                entry.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await entry.task

        # 仅在 task 确实结束后才 pop，避免 task 仍在运行时从注册表移除
        if entry.task.done():
            self._active.pop(agent_id, None)
        logger.debug("[InProcessBackend] shut down %s", agent_id)
        return True

    def list_agents(self) -> list[tuple[str, bool, float]]:
        """返回 (agent_id, is_running, duration_seconds) 元组列表。"""
        now = time.time()
        result = []
        for agent_id, entry in self._active.items():
            is_running = not entry.task.done()
            duration = now - entry.started_at
            result.append((agent_id, is_running, duration))
        return result

    async def shutdown_all(self, *, force: bool = False, timeout: float = 10.0) -> None:
        """终止所有活跃代理。"""
        agent_ids = list(self._active.keys())
        await asyncio.gather(
            *(self.shutdown(aid, force=force, timeout=timeout) for aid in agent_ids),
            return_exceptions=True,
        )
