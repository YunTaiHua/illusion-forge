"""workspace 模块测试：工作目录校验、规范化、首次登录判定。"""
from __future__ import annotations

from pathlib import Path

import pytest

from illusion_forge.config.settings import Settings
from illusion_forge.cli.workspace import (
    is_first_login,
    validate_and_normalize,
)


class TestValidateAndNormalize:
    def test_existing_dir(self, tmp_path: Path):
        result, err = validate_and_normalize(str(tmp_path))
        assert err == ""
        assert result == tmp_path.resolve()

    def test_creates_missing_dir(self, tmp_path: Path):
        target = tmp_path / "new_project"
        result, err = validate_and_normalize(str(target))
        assert err == ""
        assert result == target.resolve()
        assert target.exists()

    def test_empty_string(self):
        result, err = validate_and_normalize("")
        assert result is None
        assert err == ""

    def test_whitespace_only(self):
        result, err = validate_and_normalize("   ")
        assert result is None
        assert err == ""

    def test_expanduser(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        result, err = validate_and_normalize("~/myproject")
        assert err == ""
        assert result == (tmp_path / "myproject").resolve()

    def test_invalid_path(self, tmp_path: Path):
        # 使用包含非法字符的路径（Windows 上 <> 非法）
        bad_path = str(tmp_path / "<invalid>")
        result, err = validate_and_normalize(bad_path)
        assert result is None
        assert err != ""


class TestIsFirstLogin:
    def test_no_envs_no_wd(self):
        s = Settings()
        assert is_first_login(s) is True

    def test_with_envs(self):
        s = Settings(env_1={"api_format": "anthropic", "model_1": "claude-sonnet-4-6"})
        assert is_first_login(s) is False

    def test_with_working_directory(self):
        s = Settings(working_directory="/tmp/some_project")
        assert is_first_login(s) is False
