"""
MCP 资源列表工具
================

本模块提供列出 MCP 资源的功能。

主要组件：
    - ListMcpResourcesTool: 列出 MCP 服务器上的资源

使用示例：
    >>> from illusion_forge.tools import ListMcpResourcesTool
    >>> tool = ListMcpResourcesTool(manager)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from illusion_forge.mcp.client import McpClientManager
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult


class ListMcpResourcesToolInput(BaseModel):
    """MCP 资源列表参数。"""

    server: str | None = Field(
        default=None,
        description="Optional MCP server name to filter resources",
    )


class ListMcpResourcesTool(BaseTool[ListMcpResourcesToolInput]):
    """列出从已连接服务器发现的 MCP 资源。

    用于查看可用的 MCP 服务器资源。
    """

    name = "list_mcp_resources"
    description = """List available resources from configured MCP servers.
Each result line is formatted as "server_name:uri description".

Parameters:
- server (optional): The name of a specific MCP server to get resources from. If not provided,
  resources from all servers will be returned. If the specified server is unknown or has no
  resources, a diagnostic message is returned."""
    input_model = ListMcpResourcesToolInput

    def __init__(self, manager: McpClientManager) -> None:
        self._manager = manager

    def is_read_only(self, arguments: ListMcpResourcesToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: ListMcpResourcesToolInput, context: ToolExecutionContext) -> ToolResult:
        del context
        server = (arguments.server or "").strip() or None
        # 获取资源（支持按 server 过滤）
        resources = self._manager.list_resources(server_name=server)
        if not resources:
            statuses_getter = getattr(self._manager, "list_statuses", None)
            if callable(statuses_getter):
                statuses: Any = statuses_getter()
                if server is not None:
                    status = next((item for item in statuses if item.name == server), None)
                    if status is None:
                        return ToolResult(output=f"Unknown MCP server: {server}", is_error=True)
                    detail = f" ({status.detail})" if status.detail else ""
                    return ToolResult(
                        output=f"(no MCP resources on server '{server}', state={status.state}{detail})"
                    )
                connected = [item.name for item in statuses if item.state == "connected"]
                if connected:
                    return ToolResult(
                        output=f"(no MCP resources from connected servers: {', '.join(connected)})"
                    )
            return ToolResult(output="(no MCP resources)")
        return ToolResult(
            output="\n".join(f"{item.server_name}:{item.uri} {item.description}".strip() for item in resources)
        )
