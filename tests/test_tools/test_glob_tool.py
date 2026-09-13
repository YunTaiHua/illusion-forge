"""
Glob 工具测试
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from illusion_forge.tools.base import ToolResult


@pytest.mark.asyncio
async def test_glob_tool_basic():
    """测试 glob 工具基本功能"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.glob_tool import GlobTool, GlobToolInput
    tool = GlobTool()
    # 模拟 rg 输出
    mock_output = "file1.py\nfile2.py\nsubdir/file3.py\n"
    with patch("illusion_forge.tools.glob_tool.run_rg_checked", new_callable=AsyncMock) as mock_rg:
        mock_rg.return_value = (mock_output, None)
        arguments = GlobToolInput(
            pattern="**/*.py",
            root="/test",
        )
        context = ToolExecutionContext(cwd=Path.cwd())
        result = await tool.execute(arguments, context)
        assert "file1.py" in result.output
        assert "file2.py" in result.output
        assert "subdir/file3.py" in result.output


@pytest.mark.asyncio
async def test_glob_tool_no_matches():
    """测试 glob 工具无匹配"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.glob_tool import GlobTool, GlobToolInput
    tool = GlobTool()
    with patch("illusion_forge.tools.glob_tool.run_rg_checked", new_callable=AsyncMock) as mock_rg:
        mock_rg.return_value = ("", None)
        arguments = GlobToolInput(
            pattern="**/*.xyz",
            root="/test",
        )
        context = ToolExecutionContext(cwd=Path.cwd())
        result = await tool.execute(arguments, context)
        assert "未找到" in result.output or "No matches" in result.output or "(no matches)" in result.output or result.output == ""


@pytest.mark.asyncio
async def test_glob_tool_error():
    """测试 glob 工具错误处理"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.glob_tool import GlobTool, GlobToolInput
    tool = GlobTool()
    with patch("illusion_forge.tools.glob_tool.run_rg_checked", new_callable=AsyncMock) as mock_rg:
        mock_rg.return_value = (None, "test error")
        arguments = GlobToolInput(
            pattern="**/*.py",
            root="/test",
        )
        context = ToolExecutionContext(cwd=Path.cwd())
        result = await tool.execute(arguments, context)
        assert result.is_error


@pytest.mark.asyncio
async def test_glob_tool_absolute_path():
    """测试 glob 工具绝对路径处理"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.glob_tool import GlobTool, GlobToolInput
    tool = GlobTool()
    # 模拟 rg 输出
    mock_output = "file1.py\n"
    with patch("illusion_forge.tools.glob_tool.run_rg_checked", new_callable=AsyncMock) as mock_rg:
        mock_rg.return_value = (mock_output, None)
        arguments = GlobToolInput(
            pattern="E:/test/**/*.py",
        )
        context = ToolExecutionContext(cwd=Path.cwd())
        result = await tool.execute(arguments, context)
        assert "file1.py" in result.output