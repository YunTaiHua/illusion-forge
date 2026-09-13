"""
项目级权限加载模块
================

本模块提供从项目目录加载权限配置的功能。

主要功能：
    - load_project_permissions: 加载项目级权限配置
    - filter_rules_by_permissions: 根据权限配置过滤 rules 文件列表

使用示例：
    >>> from illusion_forge.permissions.loader import load_project_permissions, filter_rules_by_permissions
    >>> perms = load_project_permissions("/path/to/project")
    >>> filtered_rules = filter_rules_by_permissions(rule_files, perms)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from illusion_forge.config.paths import get_project_config_dir
from illusion_forge.permissions.schemas import ProjectPermissions

logger = logging.getLogger(__name__)


def load_project_permissions(cwd: str | Path) -> ProjectPermissions:
    """加载项目级权限配置

    从 `<project>/.illusion/permissions.json` 文件中读取权限配置。
    如果文件不存在或字段缺失，返回默认值。

    Args:
        cwd: 当前工作目录

    Returns:
        ProjectPermissions: 项目级权限配置对象
    """
    config_dir = get_project_config_dir(cwd)
    permissions_file = config_dir / "permissions.json"

    if not permissions_file.exists():
        return ProjectPermissions()

    try:
        raw = json.loads(permissions_file.read_text(encoding="utf-8"))
        return ProjectPermissions.model_validate(raw)
    except (json.JSONDecodeError, OSError, ValidationError) as exc:
        logger.warning("Failed to load project permissions from %s: %s", permissions_file, exc)
        return ProjectPermissions()


def filter_rules_by_permissions(
    rule_files: list[Path],
    project_permissions: ProjectPermissions,
) -> list[Path]:
    """根据权限配置过滤 rules 文件列表

    Args:
        rule_files: rules 文件路径列表
        project_permissions: 项目级权限配置对象

    Returns:
        list[Path]: 过滤后的 rules 文件路径列表
    """
    # 检查是否禁用所有 rules
    if "*" in project_permissions.denied_rules:
        return []

    # 过滤掉被禁用的 rules
    return [f for f in rule_files if f.stem not in project_permissions.denied_rules]


def is_rules_disabled(project_permissions: ProjectPermissions) -> bool:
    """检查是否禁用所有 rules

    Args:
        project_permissions: 项目级权限配置对象

    Returns:
        bool: 是否禁用所有 rules
    """
    return "*" in project_permissions.denied_rules
