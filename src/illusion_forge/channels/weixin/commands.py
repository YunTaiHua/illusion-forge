"""微信侧斜杠命令处理
====================

继承通用斜杠命令基类，微信无专属命令逻辑。
"""
from __future__ import annotations

from illusion_forge.channels.base_commands import BaseCommandHandler


class WeixinCommandHandler(BaseCommandHandler):
    """微信侧斜杠命令处理器（继承通用基类）

    当前无微信专属命令逻辑，完全复用基类的 7 个命令。
    """
