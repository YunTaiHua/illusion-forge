"""
团队删除工具
============

本模块提供 team_delete 工具，用于清理团队相关资源。
"""

from __future__ import annotations

import json
import os

from pydantic import BaseModel

from illusion_forge.state import AppStateStore
from illusion_forge.swarm.team_helpers import (
    TEAM_LEAD_NAME,
    cleanup_team_directories,
    read_team_file,
    unregister_team_for_session_cleanup,
)
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult


class TeamDeleteToolInput(BaseModel):
    """team_delete 输入参数（无参数）。"""


class TeamDeleteTool(BaseTool[TeamDeleteToolInput]):
    """删除当前团队并清理关联目录。"""

    name = "team_delete"
    description = """# TeamDelete

Remove team and task directories when the swarm work is complete.

This operation:
- Removes the team directory (`~/.illusion/teams/{team-name}/`)
- Removes the task directory (`~/.illusion/data/tasks/{team-name}/`)
- Clears team context from the current session

**IMPORTANT**: TeamDelete will fail if the team still has active members. Gracefully terminate teammates via `SendMessage` first, then call TeamDelete after all teammates have shut down.

Use this when all teammates have finished their work and you want to clean up the team resources. The team name is automatically determined from the current session's team context.
"""
    input_model = TeamDeleteToolInput

    async def execute(self, arguments: TeamDeleteToolInput, context: ToolExecutionContext) -> ToolResult:
        del arguments
        app_state_store = context.metadata.get("app_state_store")

        team_name: str | None = None
        if isinstance(app_state_store, AppStateStore):
            team_context = app_state_store.get().team_context
            if isinstance(team_context, dict):
                raw = team_context.get("teamName")
                if isinstance(raw, str) and raw.strip():
                    team_name = raw

        if team_name:
            team_file = read_team_file(team_name)
            if team_file:
                members = team_file.get("members", [])
                if isinstance(members, list):
                    non_lead_members = [
                        member
                        for member in members
                        if isinstance(member, dict) and member.get("name") != TEAM_LEAD_NAME
                    ]
                    active_members = [
                        member
                        for member in non_lead_members
                        if member.get("isActive", member.get("is_active", True)) is not False
                    ]
                    if active_members:
                        member_names = ", ".join(str(member.get("name", "")) for member in active_members)
                        output = {
                            "success": False,
                            "message": (
                                f"Cannot cleanup team with {len(active_members)} active member(s): "
                                f"{member_names}. Use SendMessage to gracefully terminate teammates first."
                            ),
                            "team_name": team_name,
                        }
                        return ToolResult(output=json.dumps(output, ensure_ascii=False))

            cleanup_team_directories(team_name)
            unregister_team_for_session_cleanup(team_name)
            os.environ.pop("ILLUSION_TASK_LIST_ID", None)

        if isinstance(app_state_store, AppStateStore):
            app_state_store.set(team_context=None)

        output = {
            "success": True,
            "message": (
                f'Cleaned up directories and worktrees for team "{team_name}"'
                if team_name
                else "No team name found, nothing to clean up"
            ),
            "team_name": team_name,
        }
        return ToolResult(output=json.dumps(output, ensure_ascii=False))

