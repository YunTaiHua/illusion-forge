"""illusion-forge set 命令测试"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from illusion_forge.cli import app
from illusion_forge.config.settings import load_settings

runner = CliRunner()


def test_set_no_arg_shows_current(tmp_path: Path, monkeypatch):
    """无参数且已有 working_directory 时显示当前值"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({
        "ui_language": "zh-CN",
        "working_directory": str(tmp_path / "existing_project"),
    }))
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(config_dir))

    result = runner.invoke(app, ["set"])
    assert result.exit_code == 0
    assert "existing_project" in result.output


def test_set_no_arg_shows_usage(tmp_path: Path, monkeypatch):
    """无参数且无 working_directory 时显示用法"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({
        "ui_language": "zh-CN",
    }))
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(config_dir))

    result = runner.invoke(app, ["set"])
    assert result.exit_code == 0
    assert "illusion-forge set" in result.output


def test_set_with_valid_path(tmp_path: Path, monkeypatch):
    """传入合法存在的路径，settings.working_directory 更新"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({
        "ui_language": "zh-CN",
    }))
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(config_dir))

    target = tmp_path / "my_project"
    target.mkdir()

    result = runner.invoke(app, ["set", str(target)])
    assert result.exit_code == 0
    settings = load_settings()
    assert settings.working_directory == str(target.resolve())


def test_set_creates_missing_dir(tmp_path: Path, monkeypatch):
    """传入不存在的路径，目录自动创建并 settings 更新"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({
        "ui_language": "zh-CN",
    }))
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(config_dir))

    target = tmp_path / "new_project"

    result = runner.invoke(app, ["set", str(target)])
    assert result.exit_code == 0
    assert target.exists()
    settings = load_settings()
    assert settings.working_directory == str(target.resolve())


def test_set_with_invalid_path(tmp_path: Path, monkeypatch):
    """传入非法路径，退出码 1，settings 未修改"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({
        "ui_language": "zh-CN",
    }))
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(config_dir))

    # 使用包含非法字符的路径
    invalid_path = str(tmp_path / "<invalid>")

    result = runner.invoke(app, ["set", invalid_path])
    assert result.exit_code == 1
    settings = load_settings()
    assert settings.working_directory is None
