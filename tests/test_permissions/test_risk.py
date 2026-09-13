"""风险分级模块测试

覆盖高危命令识别（rm、git restore、Remove-Item 等）与工具分级。
"""
from __future__ import annotations

import pytest

from illusion_forge.permissions.risk import (
    RiskLevel,
    classify_command_risk,
    classify_tool_risk,
    is_high_risk_command,
)


@pytest.mark.parametrize(
    "command",
    [
        "rm file.txt",
        "rm -rf build",
        "rm -fr build",
        "rm -f build",
        "rm -r build",
        "rmdir emptydir",
        "shred secret.txt",
        "sudo rm -rf /tmp/x",
        "env rm -f x",
        "time rm x",
        "git restore file.py",
        "git reset --hard HEAD~2",
        "git clean -f",
        "git clean -fd",
        "git checkout -- file.py",
        "git stash drop",
        "git stash clear",
        "git branch -D feature",
        "git push --force",
        "git push -f",
        "truncate -s 0 log.txt",
        "echo ok && rm -rf /tmp/x",
        "cd /tmp; rm -f x",
        "rm -rf /",
    ],
)
def test_high_risk_commands_detected(command):
    """各类破坏性命令应被识别为高危。"""
    assert is_high_risk_command(command), f"应识别为高危: {command}"
    assert classify_command_risk(command) == RiskLevel.HIGH


@pytest.mark.parametrize(
    "command",
    [
        "Remove-Item file.txt",
        "Remove-Item -Recurse build",
        "Remove-Item -Force file.txt",
        "Del file.txt",
        "Erase file.txt",
        "rd emptydir",
        "rmdir emptydir",
        "Remove-ItemProperty key value",
        "Clear-Content file.txt",
        "Clear-Item file.txt",
        "Format-Volume -DriveLetter C",
    ],
)
def test_high_risk_powershell_detected(command):
    """PowerShell 破坏性命令应被识别为高危。"""
    assert is_high_risk_command(command), f"应识别为高危: {command}"


@pytest.mark.parametrize(
    "command",
    [
        "ls",
        "ls -la",
        "cat file.txt",
        "git status",
        "git diff",
        "git log --oneline",
        "grep foo bar.py",
        "pwd",
        "which git",
        "echo hello",
        "docker ps",
    ],
)
def test_read_only_commands_low_risk(command):
    """只读命令应被识别为 LOW。"""
    assert classify_command_risk(command) == RiskLevel.LOW, f"应为 LOW: {command}"


@pytest.mark.parametrize(
    "command",
    [
        "git add .",
        "npm install",
        "pip install requests",
        "mkdir build",
        "touch newfile.txt",
        "docker build -t x .",
    ],
)
def test_mutation_commands_medium_risk(command):
    """一般变更命令应被识别为 MEDIUM。"""
    assert classify_command_risk(command) == RiskLevel.MEDIUM, f"应为 MEDIUM: {command}"
    assert not is_high_risk_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "command sudo rm -rf /",
        "sudo sudo rm -rf /",
        "env sudo rm -rf /",
        "FOO=bar rm -rf x",
        "FOO=bar sudo rm -rf /",
        "nice -n 5 rm -rf /",
        "sudo env command rm -rf /",
        "FOO=1 BAR=2 rm file.txt",
    ],
)
def test_high_risk_command_wrapper_bypass_detected(command):
    """包装器/环境变量前缀伪装不应绕过高危识别。"""
    assert is_high_risk_command(command), f"应识别为高危: {command}"
    assert classify_command_risk(command) == RiskLevel.HIGH


def test_empty_command_is_low():
    assert classify_command_risk("") == RiskLevel.LOW
    assert classify_command_risk(None if False else "   ") == RiskLevel.LOW


def test_tool_risk_read_only():
    assert classify_tool_risk(tool_name="read_file", is_read_only=True) == RiskLevel.LOW


def test_tool_risk_mutating():
    assert classify_tool_risk(tool_name="write_file", is_read_only=False) == RiskLevel.MEDIUM


def test_tool_risk_command_priority():
    """命令型工具以命令内容为准。"""
    assert (
        classify_tool_risk(tool_name="bash", is_read_only=False, command="rm -rf x")
        == RiskLevel.HIGH
    )
    assert (
        classify_tool_risk(tool_name="bash", is_read_only=False, command="git status")
        == RiskLevel.LOW
    )


def test_custom_dangerous_bash_used_instead_of_builtin():
    """自定义 bash 高危正则应覆盖内置默认。"""
    custom = [r"^\s*my-dangerous-command\b"]
    # 自定义规则命中
    assert classify_command_risk("my-dangerous-command foo", dangerous_bash=custom) == RiskLevel.HIGH
    # 内置规则在自定义模式下不再生效（用户改出问题自负）
    assert classify_command_risk("rm -rf x", dangerous_bash=custom) != RiskLevel.HIGH


def test_custom_dangerous_powershell_used_instead_of_builtin():
    """自定义 powershell 高危正则应覆盖内置默认。"""
    custom = [r"^\s*My-Foo\b"]
    assert classify_command_risk("My-Foo bar", dangerous_powershell=custom, dangerous_bash=[]) == RiskLevel.HIGH
    assert classify_command_risk("Remove-Item x", dangerous_powershell=custom, dangerous_bash=[]) != RiskLevel.HIGH


def test_empty_custom_patterns_fall_back_to_builtin():
    """空自定义列表应回退到内置默认。"""
    assert classify_command_risk("rm x", dangerous_bash=[]) == RiskLevel.HIGH
    assert classify_command_risk("Remove-Item x", dangerous_powershell=[]) == RiskLevel.HIGH


def test_custom_read_only_commands_override_builtin():
    """自定义只读命令前缀应覆盖内置默认（LOW 分级透明可改）。"""
    custom = ["myreadcmd"]
    # 自定义前缀命中 → LOW
    assert classify_command_risk("myreadcmd foo", read_only_commands=custom) == RiskLevel.LOW
    # 内置前缀在自定义模式下不再生效（用户改出问题自负）
    assert classify_command_risk("ls -la", read_only_commands=custom) != RiskLevel.LOW


def test_custom_medium_risk_tools_override_builtin():
    """自定义 MEDIUM 变更类工具应覆盖内置默认。"""
    custom = ["my_tool"]
    assert (
        classify_tool_risk(tool_name="my_tool", is_read_only=False, medium_risk_tools=custom)
        == RiskLevel.MEDIUM
    )
    # 内置工具不在自定义列表时不再判 MEDIUM（仍为 MEDIUM 兜底，但语义上由用户决定）
    assert (
        classify_tool_risk(tool_name="write_file", is_read_only=False, medium_risk_tools=custom)
        == RiskLevel.MEDIUM  # 其余变更工具仍 MEDIUM
    )