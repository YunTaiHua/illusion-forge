"""
MCP 斜杠命令
=============

/mcp — 显示 MCP 状态和管理认证
"""

from __future__ import annotations

from illusion_forge.commands.types import CommandContext, CommandResult
from illusion_forge.config.settings import load_settings, save_settings


async def mcp_handler(args: str, context: CommandContext) -> CommandResult:
    """MCP 命令处理器"""
    settings = load_settings()
    tokens = args.split()
    if tokens and tokens[0] == "auth" and len(tokens) >= 3:
        server_name = tokens[1]
        config = settings.mcp_servers.get(server_name)
        if config is None:
            return CommandResult(message=f"Unknown MCP server: {server_name}")

        if len(tokens) == 3:
            mode = "bearer"
            key = None
            value = tokens[2]
        elif len(tokens) == 4:
            mode = tokens[2]
            key = None
            value = tokens[3]
        elif len(tokens) == 5:
            mode = tokens[2]
            key = tokens[3]
            value = tokens[4]
        else:
            return CommandResult(
                message="Usage: /mcp auth SERVER TOKEN | /mcp auth SERVER [bearer|env] VALUE | /mcp auth SERVER header KEY VALUE"
            )

        if hasattr(config, "headers"):
            if mode not in {"bearer", "header"}:
                return CommandResult(message="HTTP/WS MCP auth supports bearer or header modes.")
            header_key = key or "Authorization"
            header_value = (
                f"Bearer {value}" if mode == "bearer" and header_key == "Authorization" else value
            )
            headers = dict(getattr(config, "headers", {}) or {})
            headers[header_key] = header_value
            settings.mcp_servers[server_name] = config.model_copy(update={"headers": headers})
        elif hasattr(config, "env"):
            if mode not in {"bearer", "env"}:
                return CommandResult(message="stdio MCP auth supports bearer or env modes.")
            env_key = key or "MCP_AUTH_TOKEN"
            env_value = f"Bearer {value}" if mode == "bearer" else value
            env = dict(getattr(config, "env", {}) or {})
            env[env_key] = env_value
            settings.mcp_servers[server_name] = config.model_copy(update={"env": env})
        else:
            return CommandResult(message=f"Server {server_name} does not support auth updates")
        save_settings(settings)
        return CommandResult(message=f"Saved MCP auth for {server_name}. Restart session to reconnect.")
    return CommandResult(message=context.mcp_summary or "No MCP servers configured.")
