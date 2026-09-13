"""
项目级权限配置测试
================

测试 ProjectPermissions 数据类的功能。
"""

from __future__ import annotations

from illusion_forge.permissions.schemas import ProjectPermissions


class TestProjectPermissions:
    """ProjectPermissions 数据类测试"""

    def test_default_values(self) -> None:
        """测试默认值"""
        perms = ProjectPermissions()
        assert perms.denied_skills == []
        assert perms.denied_hooks == []
        assert perms.denied_plugins == []
        assert perms.denied_mcp_servers == []
        assert perms.denied_memory is False
        assert perms.denied_rules == []

    def test_custom_values(self) -> None:
        """测试自定义值"""
        perms = ProjectPermissions(
            denied_skills=["skill-a", "skill-b"],
            denied_hooks=["PreToolUse"],
            denied_plugins=["plugin-a"],
            denied_mcp_servers=["server-a"],
            denied_memory=True,
            denied_rules=["rule-a", "rule-b"],
        )
        assert perms.denied_skills == ["skill-a", "skill-b"]
        assert perms.denied_hooks == ["PreToolUse"]
        assert perms.denied_plugins == ["plugin-a"]
        assert perms.denied_mcp_servers == ["server-a"]
        assert perms.denied_memory is True
        assert perms.denied_rules == ["rule-a", "rule-b"]

    def test_wildcard(self) -> None:
        """测试通配符"""
        perms = ProjectPermissions(
            denied_skills=["*"],
            denied_hooks=["*"],
            denied_plugins=["*"],
            denied_mcp_servers=["*"],
            denied_rules=["*"],
        )
        assert perms.denied_skills == ["*"]
        assert perms.denied_hooks == ["*"]
        assert perms.denied_plugins == ["*"]
        assert perms.denied_mcp_servers == ["*"]
        assert perms.denied_rules == ["*"]
