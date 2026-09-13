"""Tests for team_create and team_delete tools."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from illusion_forge.state import AppState, AppStateStore
from illusion_forge.swarm.team_helpers import read_team_file, write_team_file
from illusion_forge.tasks import get_task_manager
from illusion_forge.tools.base import ToolExecutionContext
from illusion_forge.tools.team_create_tool import TeamCreateTool, TeamCreateToolInput
from illusion_forge.tools.team_delete_tool import TeamDeleteTool, TeamDeleteToolInput


def _context(tmp_path: Path, app_state_store: AppStateStore) -> ToolExecutionContext:
    return ToolExecutionContext(
        cwd=tmp_path,
        metadata={
            "app_state_store": app_state_store,
            "session_id": "sess-1",
        },
    )


@pytest.mark.asyncio
async def test_team_create_and_delete_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ILLUSION_TASK_LIST_ID", "")

    store = AppStateStore(AppState(model="demo-model", permission_mode="default"))
    context = _context(tmp_path, store)

    create_result = await TeamCreateTool().execute(
        TeamCreateToolInput(team_name="demo-team", description="Demo team"),
        context,
    )
    assert create_result.is_error is False
    payload = json.loads(create_result.output)
    assert payload["team_name"] == "demo-team"
    assert payload["lead_agent_id"] == "team-lead@demo-team"
    assert os.environ.get("ILLUSION_TASK_LIST_ID") == "demo-team"

    team_file = read_team_file("demo-team")
    assert team_file is not None
    assert team_file["name"] == "demo-team"
    assert store.get().team_context is not None

    delete_result = await TeamDeleteTool().execute(TeamDeleteToolInput(), context)
    assert delete_result.is_error is False
    delete_payload = json.loads(delete_result.output)
    assert delete_payload["success"] is True
    assert read_team_file("demo-team") is None
    assert store.get().team_context is None
    assert "ILLUSION_TASK_LIST_ID" not in os.environ


@pytest.mark.asyncio
async def test_team_create_rejects_when_leader_already_has_team(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ILLUSION_TASK_LIST_ID", "")

    store = AppStateStore(
        AppState(
            model="demo-model",
            permission_mode="default",
            team_context={"teamName": "existing-team"},
        )
    )
    context = _context(tmp_path, store)

    result = await TeamCreateTool().execute(
        TeamCreateToolInput(team_name="new-team"),
        context,
    )
    assert result.is_error is True
    assert "Already leading team" in result.output


@pytest.mark.asyncio
async def test_team_delete_blocks_when_non_lead_member_active(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ILLUSION_TASK_LIST_ID", "")

    store = AppStateStore(AppState(model="demo-model", permission_mode="default"))
    context = _context(tmp_path, store)

    create_result = await TeamCreateTool().execute(
        TeamCreateToolInput(team_name="demo-team"),
        context,
    )
    payload = json.loads(create_result.output)
    team_name = payload["team_name"]
    team_file = read_team_file(team_name)
    assert team_file is not None
    team_file["members"].append(
        {
            "agentId": "worker@demo-team",
            "name": "worker",
            "agentType": "worker",
            "joinedAt": 1,
            "tmuxPaneId": "",
            "cwd": str(tmp_path),
            "subscriptions": [],
            "isActive": True,
        }
    )
    write_team_file(team_name, team_file)

    delete_result = await TeamDeleteTool().execute(TeamDeleteToolInput(), context)
    assert delete_result.is_error is False
    delete_payload = json.loads(delete_result.output)
    assert delete_payload["success"] is False
    assert "Cannot cleanup team" in delete_payload["message"]


@pytest.mark.asyncio
async def test_team_switch_preserves_default_task_manager_tasks(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ILLUSION_TASK_LIST_ID", raising=False)

    store = AppStateStore(AppState(model="demo-model", permission_mode="default"))
    context = _context(tmp_path, store)

    default_manager = get_task_manager()
    default_task = default_manager.create_pending_task(
        subject="default task",
        description="created before team create",
    )

    create_result = await TeamCreateTool().execute(
        TeamCreateToolInput(team_name="demo-team"),
        context,
    )
    assert create_result.is_error is False
    assert get_task_manager().get_task(default_task.id) is None

    delete_result = await TeamDeleteTool().execute(TeamDeleteToolInput(), context)
    assert delete_result.is_error is False
    assert get_task_manager().get_task(default_task.id) is not None
