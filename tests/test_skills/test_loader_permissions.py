"""
Skills 加载器权限过滤测试
========================

测试 load_skill_registry 函数的权限过滤功能。
"""

from __future__ import annotations

import json
from pathlib import Path

from illusion_forge.skills.loader import load_skill_registry


class TestLoadSkillRegistryPermissions:
    """load_skill_registry 函数权限过滤测试"""

    def test_no_permissions(self, tmp_path: Path) -> None:
        """测试没有权限配置时加载所有 skills"""
        registry = load_skill_registry(tmp_path)
        # 应该加载内置 skills
        skills = registry.list_skills()
        assert len(skills) > 0

    def test_denied_specific_skill(self, tmp_path: Path) -> None:
        """测试禁用特定 skill"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_skills": ["debug"],
            }),
            encoding="utf-8",
        )

        registry = load_skill_registry(tmp_path)
        skills = registry.list_skills()
        skill_names = [s.name for s in skills]
        assert "debug" not in skill_names

    def test_denied_all_skills(self, tmp_path: Path) -> None:
        """测试禁用所有 skills"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_skills": ["*"],
            }),
            encoding="utf-8",
        )

        registry = load_skill_registry(tmp_path)
        skills = registry.list_skills()
        assert len(skills) == 0
