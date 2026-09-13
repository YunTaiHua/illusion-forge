"""
协调器模式模块
==============

本模块提供任务通知的 XML 序列化/反序列化功能。

主要组件：
    - TaskNotification: 已完成任务的结果结构
    - format_task_notification: 序列化为 XML
    - parse_task_notification: 从 XML 解析

使用示例：
    >>> from illusion_forge.coordinator.coordinator_mode import TaskNotification, format_task_notification
    >>> n = TaskNotification(task_id="agent-1", status="completed", summary="Done")
    >>> xml = format_task_notification(n)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# TaskNotification 数据类
# ---------------------------------------------------------------------------


@dataclass
class TaskNotification:
    """已完成代理任务的结构化结果。

    Attributes:
        task_id: 任务 ID
        status: 状态 (completed/failed/killed)
        summary: 人类可读的状态摘要
        result: 代理的最终文本响应 (可选)
        usage: 使用统计信息 (可选)
    """

    task_id: str
    """任务 ID。"""

    status: str
    """状态 (completed/failed/killed)。"""

    summary: str
    """人类可读的状态摘要。"""

    result: str | None = None
    """代理的最终文本响应。"""

    usage: dict[str, int] | None = None
    """使用统计信息。"""


# ---------------------------------------------------------------------------
# XML 序列化/反序列化
# ---------------------------------------------------------------------------

# 使用统计字段名
_USAGE_FIELDS = ("total_tokens", "tool_uses", "duration_ms")


def format_task_notification(n: TaskNotification) -> str:
    """将 TaskNotification 序列化为标准 XML envelope。

    Args:
        n: 任务通知对象

    Returns:
        str: XML 格式的字符串
    """
    parts = [
        "<task-notification>",
        f"<task-id>{n.task_id}</task-id>",
        f"<status>{n.status}</status>",
        f"<summary>{n.summary}</summary>",
    ]
    if n.result is not None:
        parts.append(f"<result>{n.result}</result>")
    if n.usage:
        parts.append("<usage>")
        for key in _USAGE_FIELDS:
            if key in n.usage:
                parts.append(f"  <{key}>{n.usage[key]}</{key}>")
        parts.append("</usage>")
    parts.append("</task-notification>")
    return "\n".join(parts)


def parse_task_notification(xml: str) -> TaskNotification:
    """从 XML 字符串解析 TaskNotification。

    Args:
        xml: XML 格式的字符串

    Returns:
        TaskNotification: 解析后的任务通知对象
    """

    def _extract(tag: str) -> str | None:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.DOTALL)
        return m.group(1).strip() if m else None

    task_id = _extract("task-id") or ""
    status = _extract("status") or ""
    summary = _extract("summary") or ""
    result = _extract("result")

    usage: dict[str, int] | None = None
    usage_block = re.search(r"<usage>(.*?)</usage>", xml, re.DOTALL)
    if usage_block:
        usage = {}
        for key in _USAGE_FIELDS:
            m = re.search(rf"<{key}>(\d+)</{key}>", usage_block.group(1))
            if m:
                usage[key] = int(m.group(1))

    return TaskNotification(
        task_id=task_id,
        status=status,
        summary=summary,
        result=result,
        usage=usage,
    )
