"""
沙箱斜杠命令
============

/sandbox — 查看沙箱状态、管理排除命令

用法：
    /sandbox              — 显示沙箱状态
    /sandbox status       — 显示沙箱状态
    /sandbox exclude <pattern>  — 添加排除命令模式
    /sandbox remove <pattern>   — 移除排除命令模式
"""

from __future__ import annotations

from typing import Any

from illusion_forge.commands.types import CommandContext, CommandResult
from illusion_forge.config.settings import load_settings, save_settings


async def sandbox_handler(args: str, context: CommandContext) -> CommandResult:
    """沙箱命令处理

    Args:
        args: 命令参数（如 "status"、"exclude npm test"）
        context: 命令上下文

    Returns:
        CommandResult 包含状态信息或操作结果
    """
    del context
    settings = load_settings()
    sandbox = settings.sandbox
    tokens = args.split(maxsplit=1) if args else []
    subcommand = tokens[0] if tokens else "status"

    if subcommand == "status" or subcommand == "":
        return _format_status(sandbox)

    if subcommand == "exclude":
        if len(tokens) < 2 or not tokens[1].strip():
            return CommandResult(message="Usage: /sandbox exclude <command pattern>\nExample: /sandbox exclude npm test")
        pattern = tokens[1].strip()
        return _add_excluded_command(sandbox, pattern, settings)

    if subcommand == "remove":
        if len(tokens) < 2 or not tokens[1].strip():
            return CommandResult(message="Usage: /sandbox remove <command pattern>")
        pattern = tokens[1].strip()
        return _remove_excluded_command(sandbox, pattern, settings)

    return CommandResult(
        message=(
            "Usage:\n"
            "  /sandbox              — Show sandbox status\n"
            "  /sandbox status       — Show sandbox status\n"
            "  /sandbox exclude <pattern> — Add excluded command\n"
            "  /sandbox remove <pattern>  — Remove excluded command"
        )
    )


def _format_status(sandbox: Any) -> CommandResult:
    """格式化沙箱状态信息"""
    lines = []

    lines.append("Sandbox status: enabled")

    if sandbox.enabled_platforms:
        lines.append(f"  Enabled platforms: {', '.join(sandbox.enabled_platforms)}")
    else:
        lines.append("  Enabled platforms: all")

    # 排除命令
    if sandbox.excluded_commands:
        lines.append(f"  Excluded commands ({len(sandbox.excluded_commands)}):")
        for cmd in sandbox.excluded_commands:
            lines.append(f"    - {cmd}")
    else:
        lines.append("  Excluded commands: none")

    # 文件系统限制
    fs = sandbox.filesystem
    if fs.allow_write and fs.allow_write != ["."]:
        lines.append(f"  Allow write: {', '.join(fs.allow_write)}")
    if fs.deny_write:
        lines.append(f"  Deny write: {', '.join(fs.deny_write)}")
    if fs.deny_read:
        lines.append(f"  Deny read: {', '.join(fs.deny_read)}")

    # 网络限制
    net = sandbox.network
    if net.allowed_domains:
        lines.append(f"  Allowed domains: {', '.join(net.allowed_domains)}")
    if net.denied_domains:
        lines.append(f"  Denied domains: {', '.join(net.denied_domains)}")

    return CommandResult(message="\n".join(lines))


def _add_excluded_command(sandbox: Any, pattern: str, settings: Any) -> CommandResult:
    """添加排除命令模式"""
    if pattern in sandbox.excluded_commands:
        return CommandResult(message=f"Command pattern '{pattern}' is already in the excluded list")

    sandbox.excluded_commands.append(pattern)
    save_settings(settings)
    return CommandResult(message=f"Added excluded command: {pattern}\nCurrent excluded list: {', '.join(sandbox.excluded_commands)}")


def _remove_excluded_command(sandbox: Any, pattern: str, settings: Any) -> CommandResult:
    """移除排除命令模式"""
    if pattern not in sandbox.excluded_commands:
        return CommandResult(message=f"Command pattern '{pattern}' is not in the excluded list")

    sandbox.excluded_commands.remove(pattern)
    save_settings(settings)
    return CommandResult(message=f"Removed excluded command: {pattern}")
