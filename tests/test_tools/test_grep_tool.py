"""
Grep 工具测试
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from illusion_forge.tools.base import ToolResult


@pytest.mark.asyncio
async def test_grep_tool_files_with_matches():
    """测试 grep 工具 files_with_matches 模式"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.grep_tool import GrepTool, GrepToolInput
    tool = GrepTool()
    # 模拟 rg 输出
    mock_output = "file1.py\nfile2.py\n"
    with patch("illusion_forge.tools.grep_tool.run_rg_checked", new_callable=AsyncMock) as mock_rg:
        mock_rg.return_value = (mock_output, None)
        arguments = GrepToolInput(
            pattern="test",
            path="/test",
            output_mode="files_with_matches",
        )
        context = ToolExecutionContext(cwd=Path.cwd())
        result = await tool.execute(arguments, context)
        assert "file1.py" in result.output
        assert "file2.py" in result.output


@pytest.mark.asyncio
async def test_grep_tool_content():
    """测试 grep 工具 content 模式"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.grep_tool import GrepTool, GrepToolInput
    tool = GrepTool()
    # 模拟 rg 输出
    mock_output = "file1.py:1:test line\nfile2.py:2:another test\n"
    with patch("illusion_forge.tools.grep_tool.run_rg_checked", new_callable=AsyncMock) as mock_rg:
        mock_rg.return_value = (mock_output, None)
        arguments = GrepToolInput(
            pattern="test",
            path="/test",
            output_mode="content",
        )
        context = ToolExecutionContext(cwd=Path.cwd())
        result = await tool.execute(arguments, context)
        assert "file1.py" in result.output
        assert "test line" in result.output


@pytest.mark.asyncio
async def test_grep_tool_count():
    """测试 grep 工具 count 模式"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.grep_tool import GrepTool, GrepToolInput
    tool = GrepTool()
    # 模拟 rg 输出
    mock_output = "file1.py:5\nfile2.py:3\n"
    with patch("illusion_forge.tools.grep_tool.run_rg_checked", new_callable=AsyncMock) as mock_rg:
        mock_rg.return_value = (mock_output, None)
        arguments = GrepToolInput(
            pattern="test",
            path="/test",
            output_mode="count",
        )
        context = ToolExecutionContext(cwd=Path.cwd())
        result = await tool.execute(arguments, context)
        assert "file1.py" in result.output
        assert "5" in result.output


@pytest.mark.asyncio
async def test_grep_tool_no_matches():
    """测试 grep 工具无匹配"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.grep_tool import GrepTool, GrepToolInput
    tool = GrepTool()
    with patch("illusion_forge.tools.grep_tool.run_rg_checked", new_callable=AsyncMock) as mock_rg:
        mock_rg.return_value = ("", None)
        arguments = GrepToolInput(
            pattern="nonexistent",
            path="/test",
        )
        context = ToolExecutionContext(cwd=Path.cwd())
        result = await tool.execute(arguments, context)
        assert "未找到匹配" in result.output or "No matches" in result.output or "(no matches)" in result.output or result.output == ""


@pytest.mark.asyncio
async def test_grep_tool_error():
    """测试 grep 工具错误处理"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.grep_tool import GrepTool, GrepToolInput
    tool = GrepTool()
    with patch("illusion_forge.tools.grep_tool.run_rg_checked", new_callable=AsyncMock) as mock_rg:
        mock_rg.return_value = (None, "test error")
        arguments = GrepToolInput(
            pattern="test",
            path="/test",
        )
        context = ToolExecutionContext(cwd=Path.cwd())
        result = await tool.execute(arguments, context)
        assert result.is_error