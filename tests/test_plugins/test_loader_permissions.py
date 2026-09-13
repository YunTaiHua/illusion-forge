"""
Plugins 加载器权限过滤测试
==========================

测试 load_plugins 函数的权限过滤功能。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from illusion_forge.plugins.loader import load_plugins


class TestLoadPluginsPermissions:
    """load_plugins 函数权限过滤测试"""

    def _create_settings(self) -> SimpleNamespace:
        """创建模拟设置对象"""
        return SimpleNamespace(
            enabled_plugins={},
        )

    def test_no_permissions(self, tmp_path: Path) -> None:
        """测试没有权限配置时加载所有插件"""
        settings = self._create_settings()
        plugins = load_plugins(settings, tmp_path)
        # 没有插件目录，应该返回空列表
        assert len(plugins) == 0

    def test_denied_specific_plugin(self, tmp_path: Path) -> None:
        """测试禁用特定插件"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_plugins": ["test-plugin"],
            }),
            encoding="utf-8",
        )

        settings = self._create_settings()
        plugins = load_plugins(settings, tmp_path)
        plugin_names = [p.manifest.name for p in plugins]
        assert "test-plugin" not in plugin_names

    def test_denied_all_plugins(self, tmp_path: Path) -> None:
        """测试禁用所有插件"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_plugins": ["*"],
            }),
            encoding="utf-8",
        )

        settings = self._create_settings()
        plugins = load_plugins(settings, tmp_path)
        assert len(plugins) == 0
