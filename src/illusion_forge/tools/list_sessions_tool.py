"""
会话列表工具
============

本模块提供列出项目可用会话的功能。

主要组件：
    - ListSessionsTool: 列出所有可用会话（ID + 摘要），供 LLM 感知
      会话 ID（配合 cron 工具的 session_id 参数使用）

使用示例：
    >>> from illusion_forge.tools import ListSessionsTool
    >>> tool = ListSessionsTool()
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult


class ListSessionsInput(BaseModel):
    """会话列表参数。

    属性：
        limit: 最大返回数量
    """

    limit: int = Field(default=20, ge=1, le=100, description="Max sessions to return")


class ListSessionsTool(BaseTool[ListSessionsInput]):
    """列出项目内所有可用会话（含当前活跃会话标注）。

    供 LLM 感知可用的会话 ID：
    - 查看当前对话的 session_id（标注 [current]）
    - 为 cron 任务的 session_id 参数选择目标会话
    """

    name = "list_sessions"
    description = """List all available conversation sessions (project-scoped) with their session IDs.

Use this to:
- Find the CURRENT session ID (marked [current]) — e.g. pass empty string '' as the cron session_id to execute in the current conversation
- Pick a specific session ID for the cron tool's session_id parameter (to run a scheduled job inside an existing conversation)

Each entry shows: session_id, summary, message count, and last update time. Sorted by most recently updated first."""
    input_model = ListSessionsInput

    def is_read_only(self, arguments: ListSessionsInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: ListSessionsInput, context: ToolExecutionContext) -> ToolResult:
        from illusion_forge.services.session_storage import list_session_snapshots

        current_sid = str(context.metadata.get("session_id") or "").strip()
        sessions = list_session_snapshots(context.cwd, limit=arguments.limit)
        if not sessions:
            return ToolResult(
                output=(
                    f"No saved sessions found.\n"
                    f"Current session: {current_sid}"
                    if current_sid
                    else "No saved sessions found."
                )
            )

        lines: list[str] = []
        if current_sid:
            lines.append(f"Current session: {current_sid}")
        lines.append(f"Sessions ({len(sessions)}):")
        for s in sessions:
            sid = str(s.get("session_id", "?"))
            summary = str(s.get("summary", ""))[:50] or "(no summary)"
            msg_count = int(s.get("message_count", 0))
            updated = str(s.get("updated_at", ""))
            marker = "  [current]" if sid == current_sid else ""
            lines.append(
                f"- {sid}  {summary}  ({msg_count} msgs, updated {updated}){marker}"
            )
        return ToolResult(output="\n".join(lines))
