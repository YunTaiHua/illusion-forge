"""
Agent 派发后端抽象模块
=====================

本模块提供代理执行的后端抽象功能。

主要组件：
    - agent_executor: 代理执行器核心模块
    - in_process: 进程内执行后端
    - subprocess_backend: 子进程执行后端
    - types: 类型定义
    - worktree: Git worktree 管理

使用示例：
    >>> from illusion_forge.swarm import InProcessBackend, SubprocessBackend
    >>> from illusion_forge.swarm.agent_executor import run_agent_in_process
"""

from __future__ import annotations

# 导入核心组件
from illusion_forge.swarm.agent_executor import (
    AgentAbortController,
    AgentExecutionContext,
    AgentResult,
    AgentSpawnConfig,
    TaskNotification,
    TeammateMessage,
    format_task_notification,
    get_active_agent,
    get_active_agent_by_name,
    get_agent_context,
    list_active_agents,
    parse_task_notification,
    resolve_agent_tools,
    run_agent_in_process,
    run_agent_subprocess,
)
from illusion_forge.swarm.in_process import InProcessBackend
from illusion_forge.swarm.subprocess_backend import SubprocessBackend
from illusion_forge.swarm.types import (
    BackendType,
    SpawnResult,
    TeammateExecutor,
    TeammateSpawnConfig,
)

# 导出列表：定义公开 API
__all__ = [
    "AgentAbortController",
    "AgentExecutionContext",
    "AgentResult",
    "AgentSpawnConfig",
    "BackendType",
    "InProcessBackend",
    "SpawnResult",
    "SubprocessBackend",
    "TaskNotification",
    "TeammateExecutor",
    "TeammateMessage",
    "TeammateSpawnConfig",
    "format_task_notification",
    "get_active_agent",
    "get_active_agent_by_name",
    "get_agent_context",
    "list_active_agents",
    "parse_task_notification",
    "resolve_agent_tools",
    "run_agent_in_process",
    "run_agent_subprocess",
]
