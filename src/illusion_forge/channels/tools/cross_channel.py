"""跨渠道消息传输工具

提供 LLM 可调用的跨渠道投递工具。当用户要求把文件或文本发送到
另一个渠道（如 QQ → 微信，或 PC 终端 → 飞书）时使用。

工具说明：
    - ListChannelSessionsTool: 列出指定渠道的活跃会话（查找 chat_id）
    - SendToChannelTool: 发送本地文件或文本消息到指定渠道会话

工作流：
    1. 用户要求跨渠道发送（如"把这个文件发到微信"/"给飞书群发条消息"）
    2. LLM 先检查系统提示词中的 "Other Enabled Channels" 章节，看目标渠道会话
    3. 若目标渠道在系统提示词中只有一个会话：LLM 直接用该 chat_id 调 send_to_channel
       若有多个会话或不在系统提示词中：调 list_channel_sessions 查找
    4. list_channel_sessions 返回一个会话：直接使用，无需询问用户
       返回多个会话：LLM 用 ask_user_question 询问用户确认目标 chat_id
    5. LLM 调 send_to_channel 发送文件或文本

设计原则：与 SendMediaTool 互补——SendMediaTool 用于当前渠道内发送，
SendToChannelTool 用于跨渠道发送。LLM 根据用户意图选择。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from illusion_forge.channels.delivery import deliver_file_to_channel
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult

if TYPE_CHECKING:
    from illusion_forge.channels.config import ChannelsConfig


class ListChannelSessionsInput(BaseModel):
    """查找渠道活跃会话工具输入

    Attributes:
        channel_name: 目标渠道名 "feishu"/"qq"/"weixin"
        limit: 最多返回多少条会话（默认 10）
    """

    channel_name: str = Field(..., description="Target channel: feishu/qq/weixin")
    limit: int = Field(default=10, description="Max sessions to return (default 10)")


class ListChannelSessionsTool(BaseTool[ListChannelSessionsInput]):
    """列出指定渠道的活跃会话

    当系统提示词中未列出目标渠道会话、或会话列表过期时，调用此工具
    查找目标渠道的活跃会话。

    返回的会话列表包含 chat_id、user_name（如有）、chat_type、last_active。
    - 若只有一个会话：LLM 直接使用该 chat_id，无需询问用户
    - 若有多个会话：LLM 将这些信息呈现给用户，让用户选择目标会话
    """

    name = "list_channel_sessions"
    description = (
        "List active sessions in a messaging channel to find a target chat_id. "
        "Use this when the user asks to send a file to another channel but hasn't "
        "specified a chat_id, AND the target channel's session list is not already "
        "visible in your system prompt (the 'Other Enabled Channels' section shows "
        "active sessions per channel — check there FIRST). "
        "If the returned list contains ONLY ONE session, use that chat_id directly "
        "to call send_to_channel — no need to ask the user. "
        "If MULTIPLE sessions are returned, present the options to the user and ask "
        "which one to send to. "
        "Do NOT ask the user for a chat_id directly — most users don't know it."
    )
    input_model = ListChannelSessionsInput

    def __init__(self, config: ChannelsConfig) -> None:
        """初始化

        Args:
            config: 全部渠道配置（用于校验目标渠道是否 enabled）
        """
        self._config = config

    async def execute(
        self, arguments: BaseModel, context: ToolExecutionContext
    ) -> ToolResult:
        """执行会话查找"""
        assert isinstance(arguments, ListChannelSessionsInput)

        # 校验目标渠道是否启用
        target_cfg = getattr(self._config, arguments.channel_name, None)
        if target_cfg is None or not getattr(target_cfg, "enabled", False):
            return ToolResult(
                output=f"Channel '{arguments.channel_name}' is not enabled",
                is_error=True,
            )

        try:
            from illusion_forge.prompts.channel_hints import list_active_sessions

            sessions = list_active_sessions(
                arguments.channel_name, self._config, limit=arguments.limit,
            )
            if not sessions:
                return ToolResult(
                    output=(
                        f"No active sessions found in '{arguments.channel_name}'. "
                        "The user may need to interact with the bot in that channel first."
                    )
                )

            # 格式化会话列表
            lines = [f"Active sessions in '{arguments.channel_name}' (most recent first):"]
            for i, s in enumerate(sessions, 1):
                parts = [f"{i}. chat_id={s.chat_id}"]
                if s.user_name and s.user_name != s.chat_id:
                    parts.append(f"user={s.user_name}")
                if s.chat_type:
                    parts.append(f"[{s.chat_type}]")
                if s.last_active:
                    parts.append(f"last_active={s.last_active}")
                lines.append(" | ".join(parts))
            lines.append("")
            if len(sessions) == 1:
                # 只有一个会话：告知 LLM 直接使用该 chat_id，无需询问用户
                lines.append(
                    "Only one active session found — use this chat_id directly "
                    "to call send_to_channel. No need to ask the user for confirmation."
                )
            else:
                # 多个会话：需要询问用户选择
                lines.append(
                    "Multiple sessions found — present these options to the user "
                    "and ask which one to send the file to. "
                    "Do NOT proceed to send without user confirmation."
                )
            return ToolResult(output="\n".join(lines))
        except (ImportError, OSError, ValueError, KeyError, AttributeError, RuntimeError) as exc:
            return ToolResult(
                output=f"Failed to list sessions: {exc}", is_error=True
            )


class SendToChannelInput(BaseModel):
    """跨渠道投递工具输入

    Attributes:
        channel_name: 目标渠道名 "feishu"/"qq"/"weixin"
        chat_id: 目标渠道中的会话 ID（通过 list_channel_sessions 查找）
        file_path: 本地文件路径（与 text 二选一）
        text: 文本消息内容（与 file_path 二选一）
        caption: 可选附注文字（仅 file_path 模式有效）
        markdown: 是否按 markdown 渲染，None=按渠道配置自动判断
        chat_type: QQ 投递目标类型 "group"/"c2c"，仅 QQ 需要
    """

    channel_name: str = Field(..., description="Target channel: feishu/qq/weixin")
    chat_id: str = Field(
        ...,
        description=(
            "Target chat ID in that channel. "
            "Find it via this order: (1) call list_channel_sessions first; "
            "(2) if unavailable, manually check "
            "~/.illusion/channels/<channel>/sessions/ and strip the prefix; "
            "(3) only if both fail, ask the user."
        ),
    )
    file_path: str = Field(
        default="",
        description="Local file path to send (mutually exclusive with 'text'; one must be set)",
    )
    text: str = Field(
        default="",
        description=(
            "Text message content to send (mutually exclusive with 'file_path'; one must be set). "
            "Supports markdown on feishu/qq (per channel config). "
            "Auto-split into chunks if exceeds channel limit."
        ),
    )
    caption: str = Field(
        default="",
        description="Optional caption text (only valid with file_path)",
    )
    markdown: bool | None = Field(
        default=None,
        description=(
            "Whether to render as markdown. None=auto per channel config "
            "(feishu=True, qq=config.markdown_support, weixin=False). "
            "Set True/False to override."
        ),
    )
    chat_type: str = Field(
        default="",
        description=(
            "QQ target type: 'group' or 'c2c'. Only needed for QQ. "
            "Empty=auto-fallback (try group first, then c2c). "
            "Explicit value avoids fallback waste."
        ),
    )


class SendToChannelTool(BaseTool[SendToChannelInput]):
    """发送文件或文本到另一个渠道的会话

    当用户要求跨渠道传输文件或文本时使用（如"把这个文件发到微信"/"给飞书群发条消息"）。
    对于当前渠道内发送，应使用 send_media 工具。

    工作流：
        1. 用户要求跨渠道发送（文件或文本）
        2. 先检查系统提示词中的 "Other Enabled Channels" 章节
        3. 若目标渠道在系统提示词中只有一个会话：直接使用该 chat_id
           若有多个会话或不在系统提示词中：调 list_channel_sessions 查找
        4. list_channel_sessions 返回一个会话：直接使用
           返回多个会话：用 ask_user_question 询问用户确认
        5. 调 send_to_channel 发送文件或文本

    文件投递调用 deliver_file_to_channel，文本投递调用 deliver_to_channel，
    均构造临时 API 客户端发送，不依赖当前渠道实例。
    """

    name = "send_to_channel"
    description = (
        "Send a local file OR a text message to a user/group in ANOTHER messaging "
        "channel. Use this when the user asks to send something to a different "
        "channel (e.g., from QQ to WeChat, or from PC terminal to Feishu). "
        "For sending within the current channel, use send_media instead. "
        "TWO MODES (mutually exclusive, one must be set): "
        "(a) file_path: send a local file (with optional caption); "
        "(b) text: send a text message (markdown supported on feishu/qq per config, "
        "auto-split into chunks if exceeds channel limit). "
        "To find the target chat_id, follow this order: "
        "(1) CHECK THE SYSTEM PROMPT FIRST: the 'Other Enabled Channels' section "
        "already lists active sessions per channel. If the target channel shows "
        "ONLY ONE session there, use that chat_id directly — no tool call needed. "
        "If it shows MULTIPLE sessions, ask the user to confirm which one to send to. "
        "(2) If the system prompt is missing or the target channel's sessions are "
        "not listed, call list_channel_sessions. If ONLY ONE session is returned, "
        "use that chat_id directly; if MULTIPLE sessions are returned, ask the "
        "user to confirm. "
        "(3) If list_channel_sessions is unavailable or returns nothing, manually "
        "check ~/.illusion/channels/<channel>/sessions/ and strip the filename "
        "prefix (feishu 'u_ou_xxx.json' -> 'ou_xxx', 'g_oc_xxx_ou_xxx.json' "
        "-> 'oc_xxx'; weixin 'u_<wxid>.json' -> '<wxid>'; qq filename is the ID). "
        "(4) Only if ALL above fail, ask the user for the chat_id directly. "
        "KEY RULE: when the target channel has exactly one active session, "
        "NEVER ask the user — just use that chat_id. "
        "QQ NOTE: set chat_type='group' or 'c2c' to avoid auto-fallback waste. "
        "Do NOT ask the user for a chat_id without first trying (1)-(3) — "
        "most users don't know it."
    )
    input_model = SendToChannelInput

    def __init__(self, config: ChannelsConfig) -> None:
        """初始化

        Args:
            config: 全部渠道配置（用于校验目标渠道是否 enabled）
        """
        self._config = config

    async def execute(
        self, arguments: BaseModel, context: ToolExecutionContext
    ) -> ToolResult:
        """执行跨渠道投递（文件或文本）"""
        assert isinstance(arguments, SendToChannelInput)

        # 校验目标渠道是否启用
        target_cfg = getattr(self._config, arguments.channel_name, None)
        if target_cfg is None or not getattr(target_cfg, "enabled", False):
            return ToolResult(
                output=f"Channel '{arguments.channel_name}' is not enabled",
                is_error=True,
            )

        # file_path 与 text 二选一
        has_file = bool(arguments.file_path)
        has_text = bool(arguments.text)
        if not has_file and not has_text:
            return ToolResult(
                output="Either 'file_path' or 'text' must be set (one of them)",
                is_error=True,
            )
        if has_file and has_text:
            return ToolResult(
                output="'file_path' and 'text' are mutually exclusive — set only one",
                is_error=True,
            )

        try:
            if has_file:
                # 文件模式
                path = Path(arguments.file_path)
                if not path.exists():
                    return ToolResult(
                        output=f"File not found: {arguments.file_path}", is_error=True
                    )
                success = await deliver_file_to_channel(
                    arguments.channel_name,
                    arguments.chat_id,
                    arguments.file_path,
                    config=self._config,
                    caption=arguments.caption,
                )
                if success:
                    return ToolResult(
                        output=f"Sent {path.name} to {arguments.channel_name}:{arguments.chat_id}"
                    )
                # 提供更详细的错误信息
                error_hint = ""
                if arguments.channel_name == "weixin":
                    error_hint = (
                        " WeChat context_token expires after 24 hours. "
                        "Ask the user to send a message to the bot in WeChat to re-establish the session."
                    )
                return ToolResult(
                    output=f"Failed to send to {arguments.channel_name}:{arguments.chat_id}.{error_hint}",
                    is_error=True,
                )
            else:
                # 文本模式
                from illusion_forge.channels.delivery import deliver_to_channel
                success = await deliver_to_channel(
                    arguments.channel_name,
                    arguments.chat_id,
                    arguments.text,
                    config=self._config,
                    markdown=arguments.markdown,
                    chat_type=arguments.chat_type,
                )
                if success:
                    return ToolResult(
                        output=f"Sent text message to {arguments.channel_name}:{arguments.chat_id}"
                    )
                # 提供更详细的错误信息
                error_hint = ""
                if arguments.channel_name == "weixin":
                    error_hint = (
                        " WeChat context_token expires after 24 hours. "
                        "Ask the user to send a message to the bot in WeChat to re-establish the session."
                    )
                return ToolResult(
                    output=f"Failed to send to {arguments.channel_name}:{arguments.chat_id}.{error_hint}",
                    is_error=True,
                )
        except (OSError, ValueError, RuntimeError) as exc:
            return ToolResult(
                output=f"Failed to send to channel: {exc}", is_error=True
            )
