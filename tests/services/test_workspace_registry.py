"""workspace_registry（Web 多工作区注册表）单元测试。"""
from __future__ import annotations

import json
from pathlib import Path

from illusion_forge.config.paths import get_workspaces_file_path
from illusion_forge.services import workspace_registry


def test_register_and_list(tmp_path: Path) -> None:
    ws_a = tmp_path / "project-a"
    ws_b = tmp_path / "project-b"
    ws_a.mkdir()
    ws_b.mkdir()

    entry, err = workspace_registry.register_workspace(str(ws_a))
    assert err is None and entry is not None
    assert entry.name == "project-a"

    entry_b, err_b = workspace_registry.register_workspace(str(ws_b))
    assert err_b is None and entry_b is not None

    registered = workspace_registry.list_registered_workspaces()
    paths = [e.path for e in registered]
    assert str(ws_a.resolve()) in paths
    assert str(ws_b.resolve()) in paths


def test_register_dedup(tmp_path: Path) -> None:
    ws = tmp_path / "dup"
    ws.mkdir()
    workspace_registry.register_workspace(str(ws))
    # 重复注册（含未规范化的等价路径）不产生重复条目
    workspace_registry.register_workspace(str(ws / "." ))
    registered = workspace_registry.list_registered_workspaces()
    assert len([e for e in registered if e.name == "dup"]) == 1


def test_register_missing_dir_rejected(tmp_path: Path) -> None:
    entry, err = workspace_registry.register_workspace(str(tmp_path / "nope"))
    assert entry is None
    assert err is not None


def test_register_file_rejected(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    entry, err = workspace_registry.register_workspace(str(f))
    assert entry is None
    assert err is not None


def test_unregister(tmp_path: Path) -> None:
    ws = tmp_path / "gone"
    ws.mkdir()
    workspace_registry.register_workspace(str(ws))
    assert workspace_registry.unregister_workspace(str(ws)) is True
    assert workspace_registry.unregister_workspace(str(ws)) is False
    assert all(e.name != "gone" for e in workspace_registry.list_registered_workspaces())


def test_resolve_views_default_first(tmp_path: Path, monkeypatch) -> None:
    default_ws = tmp_path / "default-ws"
    default_ws.mkdir()
    monkeypatch.setattr(
        workspace_registry, "get_default_workspace", lambda: str(default_ws.resolve())
    )
    extra = tmp_path / "extra"
    extra.mkdir()
    workspace_registry.register_workspace(str(extra))

    views = workspace_registry.resolve_workspace_views()
    assert views[0]["path"] == str(default_ws.resolve())
    assert views[0]["is_default"] is True
    assert views[0]["available"] is True
    assert any(v["path"] == str(extra.resolve()) and not v["is_default"] for v in views)

    # 默认工作区同时被注册时只保留一条且带默认标记
    workspace_registry.register_workspace(str(default_ws))
    views2 = workspace_registry.resolve_workspace_views()
    defaults = [v for v in views2 if v["is_default"]]
    assert len(defaults) == 1


def test_available_flag_for_deleted_dir(tmp_path: Path) -> None:
    ws = tmp_path / "vanishing"
    ws.mkdir()
    workspace_registry.register_workspace(str(ws))
    ws.rmdir()
    views = workspace_registry.resolve_workspace_views()
    view = next(v for v in views if v["name"] == "vanishing")
    assert view["available"] is False


def test_is_known_workspace(tmp_path: Path, monkeypatch) -> None:
    default_ws = tmp_path / "d"
    default_ws.mkdir()
    monkeypatch.setattr(
        workspace_registry, "get_default_workspace", lambda: str(default_ws.resolve())
    )
    other = tmp_path / "o"
    other.mkdir()
    workspace_registry.register_workspace(str(other))

    assert workspace_registry.is_known_workspace(str(default_ws)) is True
    assert workspace_registry.is_known_workspace(str(other)) is True
    assert workspace_registry.is_known_workspace(str(tmp_path / "unknown")) is False


def test_registry_file_format(tmp_path: Path) -> None:
    ws = tmp_path / "fmt"
    ws.mkdir()
    workspace_registry.register_workspace(str(ws))
    data = json.loads(get_workspaces_file_path().read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert any(e["path"] == str(ws.resolve()) for e in data["workspaces"])
