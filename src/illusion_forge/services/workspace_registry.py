"""
Web 多工作区注册表
==================

Web 端多目录空间的核心持久化：维护用户注册的目录空间列表，
供 WebBackendHost 按目录分区管理会话与运行时 bundle。

存储位置：~/.illusion/workspaces.json（{"version": 1, "workspaces": [...]}）。

默认工作区不入库：来自 settings.working_directory（或进程启动目录），
解析时动态注入到列表首位，保证任何时刻至少有一个可用工作区。

主要函数：
    - normalize_workspace_path: 规范化目录路径（expanduser + resolve）
    - register_workspace / unregister_workspace: 注册表增删
    - list_registered_workspaces: 仅列出显式注册的目录
    - resolve_workspace_views: 默认 + 注册目录合并视图（含可用性标记）
    - get_default_workspace: 当前默认工作区路径
    - is_known_workspace: 判断路径是否属于默认或已注册工作区

使用示例：
    >>> from illusion_forge.services.workspace_registry import register_workspace, resolve_workspace_views
    >>> register_workspace("D:\\projects\\demo")
    >>> views = resolve_workspace_views()
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from illusion_forge.config.paths import get_workspaces_file_path
from illusion_forge.utils.atomic_write import atomic_write_text

# 读-改-写串行化：多 WebSocket host / REST 线程可能并发操作注册表
_REGISTRY_LOCK = threading.Lock()

_REGISTRY_VERSION = 1


@dataclass
class WorkspaceEntry:
    """注册表中的单个工作区条目。

    Attributes:
        path: 规范化后的绝对路径
        name: 显示名（目录 basename）
        added_at: 注册时间戳
    """

    path: str
    name: str
    added_at: float


def normalize_workspace_path(path: str | Path) -> str:
    """规范化工作区路径为绝对路径字符串（expanduser + resolve）。

    Args:
        path: 用户输入或存储的路径

    Returns:
        str: 规范化后的绝对路径
    """
    return str(Path(str(path)).expanduser().resolve())


def _case_key(path: str) -> str:
    """返回路径去重键（Windows 大小写不敏感，其余平台原样）。"""
    return os.path.normcase(path)


def _load_registry_raw() -> dict[str, Any]:
    """读取注册表原始字典，文件缺失/损坏时返回空表。"""
    file_path = get_workspaces_file_path()
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("workspaces"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"version": _REGISTRY_VERSION, "workspaces": []}


def _save_registry_raw(registry: dict[str, Any]) -> None:
    """原子写入注册表。"""
    registry["version"] = _REGISTRY_VERSION
    atomic_write_text(
        get_workspaces_file_path(),
        json.dumps(registry, ensure_ascii=False, indent=2),
    )


def _entry_from_raw(raw: Any) -> WorkspaceEntry | None:
    """从原始 JSON 字典构造 WorkspaceEntry，非法条目返回 None。"""
    if not isinstance(raw, dict):
        return None
    path = raw.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    normalized = normalize_workspace_path(path)
    return WorkspaceEntry(
        path=normalized,
        name=Path(normalized).name or normalized,
        added_at=float(raw.get("added_at", 0) or 0),
    )


def list_registered_workspaces() -> list[WorkspaceEntry]:
    """列出显式注册的工作区（不含默认工作区）。"""
    with _REGISTRY_LOCK:
        registry = _load_registry_raw()
    entries: list[WorkspaceEntry] = []
    seen: set[str] = set()
    for raw in registry.get("workspaces", []):
        entry = _entry_from_raw(raw)
        if entry is None:
            continue
        key = _case_key(entry.path)
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    entries.sort(key=lambda e: e.added_at)
    return entries


def register_workspace(path: str | Path) -> tuple[WorkspaceEntry | None, str | None]:
    """注册一个目录空间（去重；目录必须已存在）。

    与 working_directory 设置不同，注册表不自动创建目录——
    注册的目录应是用户已有的项目目录。

    Args:
        path: 用户输入的目录路径

    Returns:
        tuple[WorkspaceEntry | None, str | None]: (条目或 None, 错误信息或 None)
    """
    normalized = normalize_workspace_path(path)
    p = Path(normalized)
    if not p.exists() or not p.is_dir():
        return None, f"目录不存在或不是文件夹: {normalized}"
    entry = WorkspaceEntry(
        path=normalized,
        name=p.name or normalized,
        added_at=time.time(),
    )
    with _REGISTRY_LOCK:
        registry = _load_registry_raw()
        workspaces = [
            raw for raw in registry.get("workspaces", [])
            if _case_key(str(raw.get("path", ""))) != _case_key(normalized)
        ]
        workspaces.append({"path": entry.path, "added_at": entry.added_at})
        registry["workspaces"] = workspaces
        _save_registry_raw(registry)
    return entry, None


def unregister_workspace(path: str | Path) -> bool:
    """移除一个已注册的工作区（默认工作区由 settings 管理，不在此列）。

    Args:
        path: 目录路径

    Returns:
        bool: 是否实际移除了条目
    """
    normalized = normalize_workspace_path(path)
    with _REGISTRY_LOCK:
        registry = _load_registry_raw()
        workspaces = registry.get("workspaces", [])
        kept = [
            raw for raw in workspaces
            if _case_key(str(raw.get("path", ""))) != _case_key(normalized)
        ]
        if len(kept) == len(workspaces):
            return False
        registry["workspaces"] = kept
        _save_registry_raw(registry)
    return True


def get_default_workspace() -> str:
    """返回当前默认工作区路径。

    解析顺序：settings.working_directory → 进程当前目录。
    """
    try:
        from illusion_forge.config.settings import load_settings

        wd = load_settings().working_directory
        if wd:
            return normalize_workspace_path(wd)
    except (OSError, ValueError):
        pass
    return str(Path.cwd())


def resolve_workspace_views() -> list[dict[str, Any]]:
    """返回默认 + 注册工作区的合并视图。

    Returns:
        list[dict]: [{path, name, is_default, available}]，默认工作区恒在首位
    """
    views: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(path: str, is_default: bool) -> None:
        key = _case_key(path)
        if key in seen:
            # 默认工作区与注册条目重复时保留默认身份
            if is_default:
                for view in views:
                    if _case_key(view["path"]) == key:
                        view["is_default"] = True
            return
        seen.add(key)
        views.append({
            "path": path,
            "name": Path(path).name or path,
            "is_default": is_default,
            "available": Path(path).is_dir(),
        })

    _append(get_default_workspace(), True)
    for entry in list_registered_workspaces():
        _append(entry.path, False)
    return views


def is_known_workspace(path: str | Path) -> bool:
    """判断路径（规范化后）是否属于默认或已注册工作区。"""
    normalized = normalize_workspace_path(path)
    key = _case_key(normalized)
    for view in resolve_workspace_views():
        if _case_key(view["path"]) == key:
            return True
    return False
