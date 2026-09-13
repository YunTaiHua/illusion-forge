"""飞书侧斜杠命令处理
====================

继承通用斜杠命令基类，飞书专属逻辑如有未来需求再在此扩展。
"""
from __future__ import annotations

from illusion_forge.channels.base_commands import BaseCommandHandler


class FeishuCommandHandler(BaseCommandHandler):
    """飞书侧斜杠命令处理器（继承通用基类）

    当前无飞书专属命令逻辑，完全复用基类的 7 个命令。
    """
