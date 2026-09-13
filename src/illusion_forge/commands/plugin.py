"""
插件斜杠命令
============

/plugin — 管理插件
"""

from __future__ import annotations

from illusion_forge.commands.types import CommandContext, CommandResult
from illusion_forge.config.settings import load_settings, save_settings
from illusion_forge.plugins.installer import install_plugin_from_path, uninstall_plugin
from illusion_forge.plugins.loader import load_plugins


async def plugin_handler(args: str, context: CommandContext) -> CommandResult:
    """插件管理命令处理器"""
    settings = load_settings()
    tokens = args.split()
    if not tokens or tokens[0] == "list":
        return CommandResult(message=context.plugin_summary or "No plugins discovered.")
    if tokens[0] == "enable" and len(tokens) == 2:
        settings.enabled_plugins[tokens[1]] = True
        save_settings(settings)
        return CommandResult(message=f"Enabled plugin '{tokens[1]}'. Restart session to reload.")
    if tokens[0] == "disable" and len(tokens) == 2:
        settings.enabled_plugins[tokens[1]] = False
        save_settings(settings)
        return CommandResult(message=f"Disabled plugin '{tokens[1]}'. Restart session to reload.")
    if tokens[0] == "install" and len(tokens) == 2:
        path = install_plugin_from_path(tokens[1])
        return CommandResult(message=f"Installed plugin to {path}")
    if tokens[0] == "uninstall" and len(tokens) == 2:
        if uninstall_plugin(tokens[1]):
            return CommandResult(message=f"Uninstalled plugin '{tokens[1]}'")
        return CommandResult(message=f"Plugin '{tokens[1]}' not found")
    plugins = load_plugins(settings, context.cwd)
    if plugins:
        return CommandResult(message=context.plugin_summary)
    return CommandResult(message="Usage: /plugin [list|enable NAME|disable NAME|install PATH|uninstall NAME]")
