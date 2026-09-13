"""测试 channel_hints 多渠道感知输出"""
from __future__ import annotations

from illusion_forge.channels.base import SessionInfo
from illusion_forge.channels.config import ChannelsConfig, FeishuChannelConfig, WeixinChannelConfig
from illusion_forge.prompts.channel_hints import get_channel_hint


def test_get_channel_hint_pc_terminal_with_enabled_channels() -> None:
    cfg = ChannelsConfig(
        feishu=FeishuChannelConfig(enabled=True, app_id="app123", app_secret="sec"),
        weixin=WeixinChannelConfig(enabled=True, account_id="bot@im.bot", token="tok"),
    )
    hint = get_channel_hint(
        current_channel=None,
        channels_config=cfg,
        active_sessions={
            "feishu": [SessionInfo(chat_id="ou_user1", user_name="张三", chat_type="dm", last_active="2026-06-28 09:15")],
            "weixin": [SessionInfo(chat_id="wxid_abc", user_name="李四", chat_type="dm", last_active="2026-06-28 10:30")],
        },
    )
    assert hint is not None
    assert "PC terminal" in hint
    assert "Feishu" in hint or "feishu" in hint
    assert "WeChat" in hint or "weixin" in hint
    assert "ou_user1" in hint
    assert "wxid_abc" in hint
    assert "send_to_channel" in hint


def test_get_channel_hint_qq_with_other_enabled_channels() -> None:
    from illusion_forge.channels.config import QQChannelConfig
    cfg = ChannelsConfig(
        qq=QQChannelConfig(enabled=True, app_id="qq_app", client_secret="sec"),
        weixin=WeixinChannelConfig(enabled=True, account_id="bot@im.bot", token="tok"),
    )
    hint = get_channel_hint(
        current_channel="qq",
        channels_config=cfg,
        qq_markdown_support=False,
        active_sessions={
            "weixin": [SessionInfo(chat_id="wxid_abc", user_name="李四", last_active="2026-06-28 10:30")],
        },
    )
    assert hint is not None
    assert "QQ Bot" in hint
    assert "WeChat" in hint or "weixin" in hint
    assert "wxid_abc" in hint
    assert "send_to_channel" in hint


def test_get_channel_hint_no_enabled_channels_returns_none() -> None:
    cfg = ChannelsConfig()
    hint = get_channel_hint(current_channel=None, channels_config=cfg)
    assert hint is None


def test_get_channel_hint_single_channel_no_other_section() -> None:
    cfg = ChannelsConfig(feishu=FeishuChannelConfig(enabled=True, app_id="x", app_secret="y"))
    hint = get_channel_hint(
        current_channel="feishu",
        channels_config=cfg,
        active_sessions={},
    )
    assert hint is not None
    assert "Feishu" in hint
    # 单渠道时不应有 "Other Enabled Channels" 章节
    assert "Other Enabled Channels" not in hint


def test_get_channel_hint_pc_terminal_no_channels_returns_none() -> None:
    cfg = ChannelsConfig()
    hint = get_channel_hint(current_channel=None, channels_config=cfg)
    assert hint is None
