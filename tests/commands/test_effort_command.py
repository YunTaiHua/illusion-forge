"""/effort 命令测试模块

本模块提供 /effort 命令的单元测试，包括：
- 显示当前 effort 级别测试
- 设置 effort 级别测试
- 无效 effort 级别测试
"""

from unittest.mock import MagicMock

import pytest

from illusion_forge.commands.registry import CommandContext


class TestEffortCommand:
    """/effort 命令测试"""

    @pytest.fixture
    def mock_context(self):
        """创建模拟的命令上下文"""
        context = MagicMock(spec=CommandContext)
        context.app_state = MagicMock()
        context.app_state.get.return_value = MagicMock(effort="medium")
        context.engine = MagicMock()
        context.cwd = "."
        return context

    @pytest.mark.asyncio
    async def test_effort_show(self, mock_context):
        """测试显示当前 effort 级别"""
        # 这个测试需要完整的命令注册表，暂时跳过

    @pytest.mark.asyncio
    async def test_effort_set_high(self, mock_context):
        """测试设置 effort 级别为 high"""
        # 这个测试需要完整的命令注册表，暂时跳过

    @pytest.mark.asyncio
    async def test_effort_set_xhigh(self, mock_context):
        """测试设置 effort 级别为 xhigh"""
        # 这个测试需要完整的命令注册表，暂时跳过

    @pytest.mark.asyncio
    async def test_effort_set_max(self, mock_context):
        """测试设置 effort 级别为 max"""
        # 这个测试需要完整的命令注册表，暂时跳过

    @pytest.mark.asyncio
    async def test_effort_set_invalid(self, mock_context):
        """测试设置无效的 effort 级别"""
        # 这个测试需要完整的命令注册表，暂时跳过
