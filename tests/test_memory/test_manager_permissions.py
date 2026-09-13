"""
Memory 管理器权限过滤测试
==========================

测试 memory 管理器的权限过滤功能。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from illusion_forge.memory.manager import (
    add_memory_entry,
    is_memory_enabled,
    list_memory_files,
    remove_memory_entry,
)


class TestIsMemoryEnabled:
    """is_memory_enabled 函数测试"""

    def test_no_permissions(self, tmp_path: Path) -> None:
        """测试没有权限配置时默认启用"""
        assert is_memory_enabled(tmp_path) is True

    def test_denied_memory(self, tmp_path: Path) -> None:
        """测试禁用记忆功能"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_memory": True,
            }),
            encoding="utf-8",
        )

        assert is_memory_enabled(tmp_path) is False


class TestListMemoryFiles:
    """list_memory_files 函数测试"""

    def test_memory_enabled(self, tmp_path: Path) -> None:
        """测试记忆功能启用时返回文件列表"""
        # 使用 get_project_memory_dir 获取正确的记忆目录
        from illusion_forge.memory.paths import get_project_memory_dir
        memory_dir = get_project_memory_dir(tmp_path)
        (memory_dir / "test.md").write_text("# Test", encoding="utf-8")

        files = list_memory_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "test.md"

    def test_memory_disabled(self, tmp_path: Path) -> None:
        """测试记忆功能禁用时返回空列表"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_memory": True,
            }),
            encoding="utf-8",
        )

        # 使用 get_project_memory_dir 获取正确的记忆目录
        from illusion_forge.memory.paths import get_project_memory_dir
        memory_dir = get_project_memory_dir(tmp_path)
        (memory_dir / "test.md").write_text("# Test", encoding="utf-8")

        files = list_memory_files(tmp_path)
        assert len(files) == 0


class TestAddMemoryEntry:
    """add_memory_entry 函数测试"""

    def test_memory_enabled(self, tmp_path: Path) -> None:
        """测试记忆功能启用时可以添加条目"""
        path = add_memory_entry(tmp_path, "Test", "# Test content")
        assert path.exists()
        assert path.read_text(encoding="utf-8").strip() == "# Test content"

    def test_memory_disabled(self, tmp_path: Path) -> None:
        """测试记忆功能禁用时抛出异常"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_memory": True,
            }),
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match="Memory is disabled"):
            add_memory_entry(tmp_path, "Test", "# Test content")


class TestRemoveMemoryEntry:
    """remove_memory_entry 函数测试"""

    def test_memory_enabled(self, tmp_path: Path) -> None:
        """测试记忆功能启用时可以删除条目"""
        # 先添加一个记忆条目
        path = add_memory_entry(tmp_path, "Test", "# Test content")
        assert path.exists()

        # 删除记忆条目
        result = remove_memory_entry(tmp_path, "test")
        assert result is True
        assert not path.exists()

    def test_memory_disabled(self, tmp_path: Path) -> None:
        """测试记忆功能禁用时抛出异常"""
        # 创建权限配置
        config_dir = tmp_path / ".illusion"
        config_dir.mkdir()
        permissions_file = config_dir / "permissions.json"
        permissions_file.write_text(
            json.dumps({
                "denied_memory": True,
            }),
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match="Memory is disabled"):
            remove_memory_entry(tmp_path, "test")
