"""
协调器模块
==========

本模块提供代理定义和任务通知功能。

主要组件：
    - AgentDefinition: 代理定义
    - TaskNotification: 任务通知
    - get_builtin_agent_definitions: 获取内置代理定义
    - get_agent_definition: 获取指定代理定义
    - get_all_agent_definitions: 获取所有代理定义
    - format_task_notification: 序列化任务通知
    - parse_task_notification: 解析任务通知

使用示例：
    >>> from illusion_forge.coordinator import AgentDefinition, get_agent_definition
    >>> from illusion_forge.coordinator import TaskNotification, format_task_notification
"""

from illusion_forge.coordinator.agent_definitions import (
    AgentDefinition,
    get_agent_definition,
    get_all_agent_definitions,
    get_builtin_agent_definitions,
)
from illusion_forge.coordinator.coordinator_mode import (
    TaskNotification,
    format_task_notification,
    parse_task_notification,
)

__all__ = [
    "AgentDefinition",
    "TaskNotification",
    "format_task_notification",
    "get_agent_definition",
    "get_all_agent_definitions",
    "get_builtin_agent_definitions",
    "parse_task_notification",
]
