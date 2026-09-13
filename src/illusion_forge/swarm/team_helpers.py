"""
Swarm 团队辅助模块
=================

本模块提供 team_create / team_delete 相关的团队文件与目录管理能力。

主要功能：
    - 团队名称规范化
    - 团队配置文件读写
    - 团队任务目录初始化与重置
    - 会话级团队清理注册
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from illusion_forge.config.paths import get_config_dir, get_data_dir

# 团队负责人固定名称
TEAM_LEAD_NAME = "team-lead"

# 当前会话中创建的团队集合（用于会话结束时兜底清理）
_SESSION_CREATED_TEAMS: set[str] = set()


def sanitize_name(name: str) -> str:
    """将名称转换为适合文件系统与标识符的 slug。"""
    sanitized = re.sub(r"[^a-zA-Z0-9]", "-", name).strip("-").lower()
    return sanitized or "team"


def get_team_dir(team_name: str) -> Path:
    """返回团队目录路径（~/.illusion/teams/{team}/）。"""
    return get_config_dir() / "teams" / sanitize_name(team_name)


def get_team_file_path(team_name: str) -> Path:
    """返回团队配置文件路径。"""
    return get_team_dir(team_name) / "config.json"


def get_team_tasks_dir(task_list_id: str) -> Path:
    """返回团队任务目录路径（~/.illusion/data/tasks/{taskListId}/）。"""
    return get_data_dir() / "tasks" / sanitize_name(task_list_id)


def read_team_file(team_name: str) -> dict[str, Any] | None:
    """读取团队配置文件。"""
    path = get_team_file_path(team_name)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        return data
    return None


def write_team_file(team_name: str, team_file: dict[str, Any]) -> None:
    """写入团队配置文件。"""
    path = get_team_file_path(team_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(team_file, handle, ensure_ascii=False, indent=2)


def ensure_tasks_dir(task_list_id: str) -> None:
    """确保团队任务目录存在。"""
    get_team_tasks_dir(task_list_id).mkdir(parents=True, exist_ok=True)


def reset_task_list(task_list_id: str) -> None:
    """重置团队任务目录内容。"""
    tasks_dir = get_team_tasks_dir(task_list_id)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    for child in tasks_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def register_team_for_session_cleanup(team_name: str) -> None:
    """将团队登记到会话结束清理列表。"""
    _SESSION_CREATED_TEAMS.add(team_name)


def unregister_team_for_session_cleanup(team_name: str) -> None:
    """从会话结束清理列表中移除团队。"""
    _SESSION_CREATED_TEAMS.discard(team_name)


def cleanup_team_directories(team_name: str) -> None:
    """清理团队目录和团队任务目录。"""
    team_file = read_team_file(team_name)
    if team_file:
        members = team_file.get("members", [])
        if isinstance(members, list):
            for member in members:
                if not isinstance(member, dict):
                    continue
                worktree_path = member.get("worktreePath")
                if isinstance(worktree_path, str) and worktree_path.strip():
                    shutil.rmtree(Path(worktree_path), ignore_errors=True)

    shutil.rmtree(get_team_dir(team_name), ignore_errors=True)
    shutil.rmtree(get_team_tasks_dir(team_name), ignore_errors=True)


async def cleanup_session_teams() -> None:
    """清理当前会话创建但未显式删除的团队。"""
    if not _SESSION_CREATED_TEAMS:
        return
    teams = list(_SESSION_CREATED_TEAMS)
    for team_name in teams:
        cleanup_team_directories(team_name)
    _SESSION_CREATED_TEAMS.clear()

