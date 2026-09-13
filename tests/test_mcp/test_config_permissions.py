"""
MCP 配置加载器权限过滤测试
==========================

测试 load_mcp_server_configs 函数的权限过滤功能。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from illusion_forge.mcp.config import load_mcp_server_configs


class TestLoadMcpServerConfigsPermissions:
    """load_mcp_server_configs 函数权限过滤测试"""

    def _create_settings(self) -> SimpleNamespace:
        """创建模拟设置对象"""
        return SimpleNamespace(
            mcp_servers={
                "server-a": SimpleNamespace(enabled=True),
                "server-b": SimpleNamespace(enabled=True),
            },
        )

    def test_no_permissions(self, tmp_path: Path) -> None:
        """测试没有权限配置时加载所有 MCP 服务器"""
        settings = self._create_settings()
        configs = load_mcp_server_configs(settings, [], tmp_path)
        assert "server-a" in configs
        assert "server-b" in configs

    def test_denied_specific_server(self, tmp_path: Path) -> None:
        """测试禁用特定 MCP 服务器"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_mcp_servers": ["server-a"],
            }),
            encoding="utf-8",
        )

        settings = self._create_settings()
        configs = load_mcp_server_configs(settings, [], tmp_path)
        assert "server-a" not in configs
        assert "server-b" in configs

    def test_denied_all_servers(self, tmp_path: Path) -> None:
        """测试禁用所有 MCP 服务器"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_mcp_servers": ["*"],
            }),
            encoding="utf-8",
        )

        settings = self._create_settings()
        configs = load_mcp_server_configs(settings, [], tmp_path)
        assert len(configs) == 0
