"""
钩子工具函数
============

共享的钩子相关工具函数。
"""

from __future__ import annotations


def wrap_in_system_reminder(content: str) -> str:
    """将内容包裹在 <system-reminder> 标签中。"""
    return f"<system-reminder>\n{content}\n</system-reminder>"
