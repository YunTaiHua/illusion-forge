"""
CLAUDE.md 发现和加载权限过滤测试
=================================

测试 discover_claude_md_files 函数的权限过滤功能。
"""

from __future__ import annotations

import json
from pathlib import Path

from illusion_forge.prompts.claudemd import discover_claude_md_files


class TestDiscoverClaudeMdFilesPermissions:
    """discover_claude_md_files 函数权限过滤测试"""

    def test_no_permissions(self, tmp_path: Path) -> None:
        """测试没有权限配置时加载所有 rules"""
        # 创建 .claude/rules 目录和规则文件
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "test-rule.md").write_text("# Test Rule", encoding="utf-8")

        files = discover_claude_md_files(tmp_path)
        rule_files = [f for f in files if "rules" in str(f)]
        assert len(rule_files) == 1
        assert rule_files[0].name == "test-rule.md"

    def test_denied_specific_rule(self, tmp_path: Path) -> None:
        """测试禁用特定 rule"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_rules": ["test-rule"],
            }),
            encoding="utf-8",
        )

        # 创建 .claude/rules 目录和规则文件
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "test-rule.md").write_text("# Test Rule", encoding="utf-8")
        (rules_dir / "another-rule.md").write_text("# Another Rule", encoding="utf-8")

        files = discover_claude_md_files(tmp_path)
        rule_files = [f for f in files if "rules" in str(f)]
        assert len(rule_files) == 1
        assert rule_files[0].name == "another-rule.md"

    def test_denied_all_rules(self, tmp_path: Path) -> None:
        """测试禁用所有 rules"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_rules": ["*"],
            }),
            encoding="utf-8",
        )

        # 创建 .claude/rules 目录和规则文件
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "test-rule.md").write_text("# Test Rule", encoding="utf-8")

        files = discover_claude_md_files(tmp_path)
        rule_files = [f for f in files if "rules" in str(f)]
        assert len(rule_files) == 0
