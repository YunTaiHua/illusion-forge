"""Tests for illusion_forge.config.paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from illusion_forge.config.paths import (
    get_config_dir,
    get_config_file_path,
    get_data_dir,
    get_logs_dir,
    get_tasks_dir,
    resolve_relative_path,
    validate_safe_path,
)


def test_get_config_dir_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ILLUSION_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    config_dir = get_config_dir()
    assert config_dir == tmp_path / ".illusion"
    assert config_dir.is_dir()


def test_get_config_dir_env_override(tmp_path: Path, monkeypatch):
    custom = tmp_path / "custom_config"
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(custom))
    config_dir = get_config_dir()
    assert config_dir == custom
    assert config_dir.is_dir()


def test_get_config_file_path(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ILLUSION_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path = get_config_file_path()
    assert path == tmp_path / ".illusion" / "settings.json"


def test_get_data_dir_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ILLUSION_CONFIG_DIR", raising=False)
    monkeypatch.delenv("ILLUSION_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    data_dir = get_data_dir()
    assert data_dir == tmp_path / ".illusion" / "data"
    assert data_dir.is_dir()


def test_get_data_dir_env_override(tmp_path: Path, monkeypatch):
    custom = tmp_path / "custom_data"
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(custom))
    data_dir = get_data_dir()
    assert data_dir == custom
    assert data_dir.is_dir()


def test_get_logs_dir_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ILLUSION_CONFIG_DIR", raising=False)
    monkeypatch.delenv("ILLUSION_LOGS_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    logs_dir = get_logs_dir()
    assert logs_dir == tmp_path / ".illusion" / "logs"
    assert logs_dir.is_dir()


def test_get_logs_dir_env_override(tmp_path: Path, monkeypatch):
    custom = tmp_path / "custom_logs"
    monkeypatch.setenv("ILLUSION_LOGS_DIR", str(custom))
    logs_dir = get_logs_dir()
    assert logs_dir == custom
    assert logs_dir.is_dir()


def test_get_tasks_dir_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ILLUSION_CONFIG_DIR", raising=False)
    monkeypatch.delenv("ILLUSION_DATA_DIR", raising=False)
    monkeypatch.delenv("ILLUSION_TASK_LIST_ID", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    tasks_dir = get_tasks_dir()
    assert tasks_dir == tmp_path / ".illusion" / "data" / "tasks"
    assert tasks_dir.is_dir()


def test_get_tasks_dir_with_task_list_id(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ILLUSION_CONFIG_DIR", raising=False)
    monkeypatch.delenv("ILLUSION_DATA_DIR", raising=False)
    monkeypatch.setenv("ILLUSION_TASK_LIST_ID", "Team Alpha/01")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    tasks_dir = get_tasks_dir()
    assert tasks_dir == tmp_path / ".illusion" / "data" / "tasks" / "Team-Alpha-01"
    assert tasks_dir.is_dir()


# ---------- validate_safe_path ----------


class TestValidateSafePath:
    """validate_safe_path 路径安全校验测试。"""

    def test_allows_normal_relative_path(self) -> None:
        """普通相对路径应通过校验。"""
        result = validate_safe_path("src/main.py")
        assert result == Path("src/main.py")

    def test_rejects_parent_traversal(self) -> None:
        """包含 .. 的路径应被拒绝。"""
        with pytest.raises(ValueError, match="Path traversal"):
            validate_safe_path("../escape")

    def test_rejects_parent_traversal_in_middle(self) -> None:
        """路径中间包含 .. 也应被拒绝。"""
        with pytest.raises(ValueError, match="Path traversal"):
            validate_safe_path("src/../etc/passwd")

    def test_rejects_home_tilde(self) -> None:
        """以 ~ 开头的路径应被拒绝。"""
        with pytest.raises(ValueError, match="Home directory"):
            validate_safe_path("~/secret")


# ---------- resolve_relative_path ----------


class TestResolveRelativePath:
    """resolve_relative_path 路径解析与安全校验测试。"""

    def test_resolves_relative_path(self, tmp_path: Path) -> None:
        """相对路径应与 base 拼接并 resolve。"""
        result = resolve_relative_path(tmp_path, "subdir/file.py")
        assert result == (tmp_path / "subdir" / "file.py").resolve()

    def test_rejects_parent_traversal(self, tmp_path: Path) -> None:
        """包含 .. 的路径应被拒绝。"""
        with pytest.raises(ValueError, match="Path traversal"):
            resolve_relative_path(tmp_path, "../escape")

    def test_rejects_home_tilde(self, tmp_path: Path) -> None:
        """以 ~ 开头的路径应被拒绝。"""
        with pytest.raises(ValueError, match="Home directory"):
            resolve_relative_path(tmp_path, "~/secret")
