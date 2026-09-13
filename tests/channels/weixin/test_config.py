"""微信渠道配置模型测试。"""
from __future__ import annotations

from illusion_forge.channels.config import (
    ChannelsConfig,
    WeixinChannelConfig,
)


def test_default_weixin_config_disabled():
    """默认配置：微信未启用。"""
    cfg = WeixinChannelConfig()
    assert cfg.enabled is False
    assert cfg.account_id == ""
    assert cfg.token == ""
    assert cfg.base_url == "https://ilinkai.weixin.qq.com"
    assert cfg.user_id == ""
    assert cfg.allow_bots is False


def test_channels_config_has_weixin_field():
    """ChannelsConfig 包含 weixin 字段。"""
    cfg = ChannelsConfig()
    assert isinstance(cfg.weixin, WeixinChannelConfig)
    assert cfg.weixin.enabled is False


def test_has_enabled_channels_with_weixin():
    """weixin 启用时 has_enabled_channels 返回 True。"""
    cfg = ChannelsConfig(weixin=WeixinChannelConfig(enabled=True, account_id="test@im.bot"))
    assert cfg.has_enabled_channels() is True
    assert "weixin" in cfg.enabled_channel_names()


def test_both_channels_enabled():
    """飞书和微信都启用。"""
    from illusion_forge.channels.config import FeishuChannelConfig
    cfg = ChannelsConfig(
        feishu=FeishuChannelConfig(enabled=True, app_id="cli"),
        weixin=WeixinChannelConfig(enabled=True, account_id="bot@im.bot"),
    )
    assert cfg.has_enabled_channels() is True
    names = cfg.enabled_channel_names()
    assert "feishu" in names
    assert "weixin" in names
