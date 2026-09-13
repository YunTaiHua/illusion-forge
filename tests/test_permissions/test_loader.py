"""
项目级权限加载测试
================

测试 load_project_permissions 函数的功能。
"""

from __future__ import annotations

import json
from pathlib import Path

from illusion_forge.permissions.loader import load_project_permissions


class TestLoadProjectPermissions:
    """load_project_permissions 函数测试"""

    def test_no_permissions_file(self, tmp_path: Path) -> None:
        """测试没有 permissions.json 文件时返回默认值"""
        perms = load_project_permissions(tmp_path)
        assert perms.denied_skills == []
        assert perms.denied_hooks == []
        assert perms.denied_plugins == []
        assert perms.denied_mcp_servers == []
        assert perms.denied_memory is False
        assert perms.denied_rules == []

    def test_empty_permissions_file(self, tmp_path: Path) -> None:
        """测试空 permissions.json 文件返回默认值"""
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text("{}", encoding="utf-8")

        perms = load_project_permissions(tmp_path)
        assert perms.denied_skills == []
        assert perms.denied_hooks == []
        assert perms.denied_plugins == []
        assert perms.denied_mcp_servers == []
        assert perms.denied_memory is False
        assert perms.denied_rules == []

    def test_full_permissions_file(self, tmp_path: Path) -> None:
        """测试完整的 permissions.json 文件"""
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_skills": ["skill-a", "skill-b"],
                "denied_hooks": ["PreToolUse"],
                "denied_plugins": ["plugin-a"],
                "denied_mcp_servers": ["server-a"],
                "denied_memory": True,
                "denied_rules": ["rule-a", "rule-b"],
            }),
            encoding="utf-8",
        )

        perms = load_project_permissions(tmp_path)
        assert perms.denied_skills == ["skill-a", "skill-b"]
        assert perms.denied_hooks == ["PreToolUse"]
        assert perms.denied_plugins == ["plugin-a"]
        assert perms.denied_mcp_servers == ["server-a"]
        assert perms.denied_memory is True
        assert perms.denied_rules == ["rule-a", "rule-b"]

    def test_partial_permissions_file(self, tmp_path: Path) -> None:
        """测试部分字段的 permissions.json 文件"""
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_skills": ["skill-a"],
                "denied_memory": True,
            }),
            encoding="utf-8",
        )

        perms = load_project_permissions(tmp_path)
        assert perms.denied_skills == ["skill-a"]
        assert perms.denied_hooks == []
        assert perms.denied_plugins == []
        assert perms.denied_mcp_servers == []
        assert perms.denied_memory is True
        assert perms.denied_rules == []

    def test_invalid_json_file(self, tmp_path: Path) -> None:
        """测试无效 JSON 文件返回默认值"""
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text("invalid json", encoding="utf-8")

        perms = load_project_permissions(tmp_path)
        assert perms.denied_skills == []
        assert perms.denied_hooks == []
        assert perms.denied_plugins == []
        assert perms.denied_mcp_servers == []
        assert perms.denied_memory is False
        assert perms.denied_rules == []

    def test_wildcard_denied_skills(self, tmp_path: Path) -> None:
        """测试通配符禁用所有 skills"""
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_skills": ["*"],
            }),
            encoding="utf-8",
        )

        perms = load_project_permissions(tmp_path)
        assert perms.denied_skills == ["*"]
