"""
权限模块
========

本模块提供 IllusionForge 权限检查和管理功能。

主要组件：
    - PermissionChecker: 权限检查器
    - PermissionDecision: 权限决策
    - PermissionMode: 权限模式
    - ProjectPermissions: 项目级权限配置
    - load_project_permissions: 加载项目级权限配置
    - filter_rules_by_permissions: 根据权限配置过滤 rules 文件列表
    - is_rules_disabled: 检查是否禁用所有 rules

使用示例：
    >>> from illusion_forge.permissions import PermissionChecker, PermissionMode, ProjectPermissions
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from illusion_forge.permissions.checker import PermissionChecker, PermissionDecision
    from illusion_forge.permissions.loader import (
        filter_rules_by_permissions,
        is_rules_disabled,
        load_project_permissions,
    )
    from illusion_forge.permissions.modes import PermissionMode
    from illusion_forge.permissions.schemas import ProjectPermissions

__all__ = [
    "PermissionChecker",
    "PermissionDecision",
    "PermissionMode",
    "ProjectPermissions",
    "filter_rules_by_permissions",
    "is_rules_disabled",
    "load_project_permissions",
]


def __getattr__(name: str) -> object:
    if name in {"PermissionChecker", "PermissionDecision"}:
        from illusion_forge.permissions.checker import PermissionChecker, PermissionDecision

        return {
            "PermissionChecker": PermissionChecker,
            "PermissionDecision": PermissionDecision,
        }[name]
    if name == "PermissionMode":
        from illusion_forge.permissions.modes import PermissionMode

        return PermissionMode
    if name == "ProjectPermissions":
        from illusion_forge.permissions.schemas import ProjectPermissions

        return ProjectPermissions
    if name in {"load_project_permissions", "filter_rules_by_permissions", "is_rules_disabled"}:
        from illusion_forge.permissions.loader import (
            filter_rules_by_permissions,
            is_rules_disabled,
            load_project_permissions,
        )

        return {
            "load_project_permissions": load_project_permissions,
            "filter_rules_by_permissions": filter_rules_by_permissions,
            "is_rules_disabled": is_rules_disabled,
        }[name]
    raise AttributeError(name)
