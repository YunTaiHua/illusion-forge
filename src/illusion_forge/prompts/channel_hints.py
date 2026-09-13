"""渠道平台感知提示词

集中管理各渠道的平台感知提示词。在渠道对话或 PC 终端启动时注入系统提示词，
让 LLM 知道当前所处的渠道、其他已启用渠道及其活跃会话。

注入门控：
    - 无 enabled 渠道时不注入（PC 终端和渠道端都跳过）
    - PC 终端（current_channel=None）+ 有 enabled 渠道 → 注入 PC 身份 + 渠道概览
    - 渠道端（current_channel="qq" 等）+ 有其他 enabled 渠道 → 注入当前身份 + 其他渠道概览
    - cron 任务子进程（ILLUSION_CRON_TASK=1）→ 不注入，避免 LLM 调用投递工具造成重复投递
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from illusion_forge.channels.base import SessionInfo
    from illusion_forge.channels.config import ChannelsConfig


def _channel_display_name(name: str) -> str:
    """渠道显示名"""
    return {
        "feishu": "Feishu (飞书)",
        "qq": "QQ Bot",
        "weixin": "WeChat (微信)",
    }.get(name, name)


def _format_session_list(sessions: list[SessionInfo]) -> str:
    """格式化会话列表为提示词文本"""
    if not sessions:
        return "(no active sessions)"
    lines = []
    for s in sessions:
        parts = [f"- {s.chat_id}"]
        if s.user_name and s.user_name != s.chat_id:
            parts.append(f"({s.user_name})")
        if s.chat_type:
            parts.append(f"[{s.chat_type}]")
        if s.last_active:
            parts.append(f"— last active {s.last_active}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _build_current_channel_section(
    current_channel: str | None,
    qq_markdown_support: bool | None,
) -> str:
    """构建当前渠道身份描述"""
    # 工具选择规则：明确区分当前渠道与跨渠道发送
    tool_rule = (
        "TOOL SELECTION RULE for sending files/images: "
        "(1) If the user asks to send a file to the CURRENT channel or does not specify a target channel, "
        "use the send_media tool. "
        "(2) The send_to_channel tool is ONLY for sending to OTHER channels — "
        "do NOT use it to send to the current channel. "
        "(3) Only use send_to_channel when the user explicitly names a DIFFERENT channel as the target."
    )
    if current_channel is None:
        return (
            "You are running in the PC terminal. "
            "Files can be sent to enabled messaging channels via the `send_to_channel` tool. "
            "On PC terminal, you MUST specify a target channel and chat_id when sending files."
        )
    if current_channel == "feishu":
        return (
            "You are conversing through Feishu (飞书). "
            "Markdown is supported and rendered via interactive cards. "
            "You can use tables, code blocks, lists, headings, and blockquotes. "
            "To send files/images to the current Feishu chat, use the send_media tool. "
            "Group chats require @mention to respond (configured per channel). "
            + tool_rule
        )
    if current_channel == "qq":
        markdown_supported = bool(qq_markdown_support)
        md_line = (
            "Markdown is supported (msg_type=2). Code blocks with triple backticks are supported. "
            if markdown_supported
            else "Markdown is NOT supported. Use plain text only; avoid backticks, tables, and headings. "
        )
        return (
            "You are conversing through QQ Bot. "
            + md_line
            + "To send files/images to the current QQ chat, use the send_media tool. "
            "Group chats require @mention and only support passive replies. "
            + tool_rule
        )
    if current_channel == "weixin":
        return (
            "You are conversing through WeChat (微信). "
            "Markdown is supported but keep messages compact and chat-friendly. "
            "Messages cannot be edited after sending; long replies are split into chunks. "
            "To send files/images to the current WeChat user, use the send_media tool. "
            "WeChat bot only supports direct messages (no group chats). "
            + tool_rule
        )
    return ""


def _build_other_channels_section(
    current_channel: str | None,
    channels_config: ChannelsConfig,
    active_sessions: dict[str, list[SessionInfo]] | None,
) -> str:
    """构建其他 enabled 渠道概览"""
    other_names = [
        n for n in channels_config.enabled_channel_names()
        if n != current_channel
    ]
    if not other_names:
        return ""

    sessions = active_sessions or {}
    lines = [
        "",
        "# Other Enabled Channels",
        (
            "The following channels are also active. Use the `send_to_channel` tool to send "
            "files OR text messages to users in THESE OTHER channels only — NOT to the current channel. "
            "For the current channel, use send_media (files) or reply directly (text)."
        ),
        "",
    ]
    for name in other_names:
        display = _channel_display_name(name)
        lines.append(f"## {display}")
        sess = sessions.get(name, [])
        lines.append("Active sessions (most recent first, max 5):")
        lines.append(_format_session_list(sess))
        lines.append("")
        lines.append(
            f'To send a file to a {_channel_display_name(name)} user, call:\n'
            f'  send_to_channel(channel_name="{name}", chat_id="<id>", file_path="...")'
        )
        lines.append("")
    return "\n".join(lines).rstrip()


def get_channel_hint(
    current_channel: str | None,
    channels_config: ChannelsConfig,
    *,
    qq_markdown_support: bool | None = None,
    active_sessions: dict[str, list[SessionInfo]] | None = None,
) -> str | None:
    """获取渠道感知提示词

    输出包含两部分：
        1. 当前渠道身份（PC 终端 / feishu / qq / weixin）
        2. 其他 enabled 渠道概览（含活跃会话列表）

    无 enabled 渠道时返回 None（不注入提示词）。
    cron 任务子进程（ILLUSION_CRON_TASK=1）也返回 None，避免 LLM 调用投递工具
    造成重复投递（cron scheduler 会自动把 stdout 投递到 deliver_to 指定的渠道）。

    Args:
        current_channel: 当前渠道名，None=PC 终端
        channels_config: 全部渠道配置
        qq_markdown_support: QQ markdown_support 配置值
        active_sessions: 各渠道活跃会话字典 {channel_name: [SessionInfo]}

    Returns:
        str | None: 提示词文本，无 enabled 渠道或 cron 任务时返回 None
    """
    # cron 任务子进程：不注入 channel_hints，避免 LLM 调用投递工具造成重复投递
    if os.environ.get("ILLUSION_CRON_TASK") == "1":
        return None

    # PC 终端：无任何 enabled 渠道时不注入
    if current_channel is None and not channels_config.has_enabled_channels():
        return None
    # 渠道端：当前渠道未 enabled 时不注入（不应发生，但防御）
    if current_channel is not None:
        current_cfg = getattr(channels_config, current_channel, None)
        if current_cfg is None or not getattr(current_cfg, "enabled", False):
            return None
        # 单渠道启用且就是当前渠道：只输出当前渠道身份，无 "Other" 章节
        if not any(
            n != current_channel and getattr(channels_config, n).enabled
            for n in ("feishu", "weixin", "qq")
        ):
            return _build_current_channel_section(current_channel, qq_markdown_support)

    current_section = _build_current_channel_section(current_channel, qq_markdown_support)
    other_section = _build_other_channels_section(current_channel, channels_config, active_sessions)
    if other_section:
        return current_section + "\n\n" + other_section
    return current_section


def list_active_sessions(
    channel_name: str,
    channels_config: ChannelsConfig,
    *,
    limit: int = 5,
) -> list[SessionInfo]:
    """枚举指定渠道的活跃会话

    按 channel_name 构造对应的 SessionStore 并调用 list_active。
    用于在系统提示词中列出其他渠道的活跃会话。

    Args:
        channel_name: 渠道名
        channels_config: 渠道配置（用于校验 enabled）
        limit: 最多返回多少条

    Returns:
        list[SessionInfo]: 活跃会话列表，无会话或渠道未启用返回空列表
    """
    from illusion_forge.config.paths import get_channels_data_dir

    cfg = getattr(channels_config, channel_name, None)
    if cfg is None or not getattr(cfg, "enabled", False):
        return []

    data_dir = get_channels_data_dir() / channel_name / "sessions"
    if not data_dir.exists():
        return []

    if channel_name == "feishu":
        from illusion_forge.channels.feishu.session_map import FeishuSessionStore
        return FeishuSessionStore(data_dir=data_dir).list_active(limit)
    if channel_name == "qq":
        from illusion_forge.channels.qq.session_map import QQSessionStore
        return QQSessionStore(data_dir=data_dir).list_active(limit)
    if channel_name == "weixin":
        from illusion_forge.channels.weixin.session_map import WeixinSessionStore
        return WeixinSessionStore(data_dir=data_dir).list_active(limit)
    return []
