"""bash_tool / powershell_tool 后台任务注册 bg_agent_tracker 的单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from illusion_forge.engine.query import BackgroundAgentTracker
from illusion_forge.tools.base import ToolExecutionContext
from illusion_forge.tools.bash_tool import BashTool, BashToolInput
from illusion_forge.tools.powershell_tool import PowerShellTool, PowerShellToolInput


def _bash_available() -> bool:
    """判断当前平台是否有可用的 bash。"""
    if sys.platform == "win32":
        from illusion_forge.utils.shell import _resolve_windows_bash

        return _resolve_windows_bash() is not None
    import shutil

    return shutil.which("bash") is not None


def _powershell_available() -> bool:
    """判断当前平台是否有可用的 PowerShell。"""
    import shutil

    return shutil.which("pwsh") is not None or shutil.which("powershell") is not None


@pytest.mark.asyncio
async def test_background_bash_registers_tracker(tmp_path: Path):
    """后台 bash 任务启动时应注册到 bg_agent_tracker。"""
    if not _bash_available():
        pytest.skip("bash is not available on this machine")

    tracker = BackgroundAgentTracker()
    context = ToolExecutionContext(
        cwd=tmp_path,
        metadata={"bg_agent_tracker": tracker},
    )
    tool = BashTool()
    # 使用一个快速完成的命令避免阻塞
    result = await tool.execute(
        BashToolInput(command="echo hello", run_in_background=True),
        context,
    )
    assert "task_id=" in result.output
    assert tracker.has_pending() is True


@pytest.mark.asyncio
async def test_background_powershell_registers_tracker(tmp_path: Path):
    """后台 powershell 任务启动时应注册到 bg_agent_tracker。"""
    if not _powershell_available():
        pytest.skip("powershell is not available on this machine")

    tracker = BackgroundAgentTracker()
    context = ToolExecutionContext(
        cwd=tmp_path,
        metadata={"bg_agent_tracker": tracker},
    )
    tool = PowerShellTool()
    result = await tool.execute(
        PowerShellToolInput(command="Write-Output hello", run_in_background=True),
        context,
    )
    assert "task_id=" in result.output
    assert tracker.has_pending() is True
