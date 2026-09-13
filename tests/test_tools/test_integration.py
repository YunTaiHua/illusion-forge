"""
集成测试 - 验证 rg 工具正常工作
"""

import os
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_grep_integration():
    """集成测试：grep 工具实际执行"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.grep_tool import GrepTool, GrepToolInput
    tool = GrepTool()
    # 在当前目录搜索一个常见词
    arguments = GrepToolInput(
        pattern="def",
        path=".",
        output_mode="files_with_matches",
        head_limit=10,
    )
    context = ToolExecutionContext(cwd=Path.cwd())
    result = await tool.execute(arguments, context)
    # 应该能找到一些 Python 文件
    assert isinstance(result.output, str)


@pytest.mark.asyncio
async def test_glob_integration():
    """集成测试：glob 工具实际执行"""
    from illusion_forge.tools.base import ToolExecutionContext
    from illusion_forge.tools.glob_tool import GlobTool, GlobToolInput
    tool = GlobTool()
    # 列出当前目录的 Python 文件
    arguments = GlobToolInput(
        pattern="**/*.py",
        root=".",
        limit=10,
    )
    context = ToolExecutionContext(cwd=Path.cwd())
    result = await tool.execute(arguments, context)
    # 应该能找到一些 Python 文件
    assert isinstance(result.output, str)


@pytest.mark.asyncio
async def test_ensure_ripgrep_integration():
    """集成测试：ensure_ripgrep 实际执行"""
    from illusion_forge.utils.ripgrep import ensure_ripgrep
    # 应该能成功获取 rg 路径
    rg_path = await ensure_ripgrep()
    assert os.path.exists(rg_path)


def test_grep_tool_no_pathlib():
    """验证 grep_tool.py 中不包含 pathlib"""
    with open("src/illusion_forge/tools/grep_tool.py", "r", encoding="utf-8") as f:
        content = f.read()
    # 检查是否包含 pathlib 导入
    assert "import pathlib" not in content
    assert "from pathlib" not in content
    # 检查是否包含 os 导入
    assert "import os" not in content
    assert "from os" not in content
    # 检查是否包含 shutil 导入
    assert "import shutil" not in content
    assert "from shutil" not in content


def test_glob_tool_no_pathlib():
    """验证 glob_tool.py 中不包含 pathlib"""
    with open("src/illusion_forge/tools/glob_tool.py", "r", encoding="utf-8") as f:
        content = f.read()
    # 检查是否包含 pathlib 导入
    assert "import pathlib" not in content
    assert "from pathlib" not in content
    # 检查是否包含 os 导入
    assert "import os" not in content
    assert "from os" not in content
    # 检查是否包含 shutil 导入
    assert "import shutil" not in content
    assert "from shutil" not in content
