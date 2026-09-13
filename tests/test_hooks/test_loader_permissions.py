"""
Hooks 加载器权限过滤测试
========================

测试 load_hook_registry 函数的权限过滤功能。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from illusion_forge.hooks.events import HookEvent
from illusion_forge.hooks.loader import load_hook_registry


class TestLoadHookRegistryPermissions:
    """load_hook_registry 函数权限过滤测试"""

    def _create_settings(self) -> SimpleNamespace:
        """创建模拟设置对象"""
        return SimpleNamespace(
            hooks={
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "echo test",
                            }
                        ],
                    }
                ],
            }
        )

    def test_no_permissions(self, tmp_path: Path) -> None:
        """测试没有权限配置时加载所有 hooks"""
        settings = self._create_settings()
        registry = load_hook_registry(settings, cwd=tmp_path)
        hooks = registry.get(HookEvent.PRE_TOOL_USE)
        assert len(hooks) > 0

    def test_denied_specific_event(self, tmp_path: Path) -> None:
        """测试禁用特定事件的 hooks"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_hooks": ["PreToolUse"],
            }),
            encoding="utf-8",
        )

        settings = self._create_settings()
        registry = load_hook_registry(settings, cwd=tmp_path)
        hooks = registry.get(HookEvent.PRE_TOOL_USE)
        assert len(hooks) == 0

    def test_denied_all_hooks(self, tmp_path: Path) -> None:
        """测试禁用所有 hooks"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_hooks": ["*"],
            }),
            encoding="utf-8",
        )

        settings = self._create_settings()
        registry = load_hook_registry(settings, cwd=tmp_path)

        # 检查所有事件都没有 hooks
        for event in HookEvent:
            hooks = registry.get(event)
            assert len(hooks) == 0
