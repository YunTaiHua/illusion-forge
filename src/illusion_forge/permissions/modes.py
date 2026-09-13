"""
权限模式定义模块
================

本模块定义 IllusionForge 支持的权限模式。

主要功能：
    - DEFAULT 模式：变更工具需要用户确认
    - PLAN 模式：阻止所有变更工具执行
    - FULL_AUTO 模式：允许所有工具自动执行（仍受沙箱限制约束）
    - YOLO 模式：绕过沙箱完全运行（不施加任何沙箱限制）

类说明：
    - PermissionMode: 权限模式枚举

使用示例：
    >>> from illusion_forge.permissions.modes import PermissionMode
    >>> mode = PermissionMode.YOLO
"""

from __future__ import annotations

from enum import Enum


class PermissionMode(str, Enum):
    """权限模式枚举
    
    定义 Agent 执行工具时的权限级别。
    
    Attributes:
        DEFAULT: 默认模式，变更工具需要用户确认
        PLAN: 计划模式，阻止所有变更工具
        FULL_AUTO: 完全自动模式，允许所有工具（仍受沙箱限制）
        YOLO: 完全绕过沙箱运行，不施加任何沙箱限制
    """

    DEFAULT = "default"  # 默认模式，变更工具需要用户确认
    PLAN = "plan"  # 计划模式，阻止所有变更工具
    FULL_AUTO = "full_auto"  # 完全自动模式（仍受沙箱限制）
    YOLO = "yolo"  # 绕过沙箱完全运行
