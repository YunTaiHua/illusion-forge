"""渠道配置模型测试。"""
from __future__ import annotations

from pathlib import Path

from illusion_forge.channels.config import (
    ChannelsConfig,
    FeishuChannelConfig,
    FeishuGroupPolicy,
    load_channels_config,
    save_channels_config,
)


def test_default_channels_config_has_disabled_feishu():
    """默认配置：飞书未启用。"""
    cfg = ChannelsConfig()
    assert cfg.feishu.enabled is False
    assert cfg.feishu.app_id == ""
    assert cfg.feishu.domain == "feishu"
    assert cfg.feishu.require_mention is True
    assert cfg.feishu.allow_bots is False
    assert cfg.feishu.group_sessions_per_user is True


def test_feishu_group_policy_defaults():
    """群组策略默认 open 模式。"""
    policy = FeishuGroupPolicy()
    assert policy.mode == "open"
    assert policy.allowlist == []
    assert policy.blacklist == []
    assert policy.admin_list == []


def test_load_missing_file_returns_empty(tmp_path: Path):
    """文件不存在时返回空配置，不崩溃。"""
    path = tmp_path / "channels.json"
    cfg = load_channels_config(path)
    assert isinstance(cfg, ChannelsConfig)
    assert cfg.feishu.enabled is False


def test_load_corrupted_file_returns_empty(tmp_path: Path):
    """文件损坏时返回空配置，不崩溃。"""
    path = tmp_path / "channels.json"
    path.write_text("{not valid json", encoding="utf-8")
    cfg = load_channels_config(path)
    assert cfg.feishu.enabled is False


def test_save_and_load_roundtrip(tmp_path: Path):
    """保存后能读回完整配置。"""
    path = tmp_path / "channels.json"
    cfg = ChannelsConfig(feishu=FeishuChannelConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="secret123",
        domain="lark",
        group_policy=FeishuGroupPolicy(mode="allowlist", allowlist=["oc_1"]),
    ))
    save_channels_config(cfg, path)
    loaded = load_channels_config(path)
    assert loaded.feishu.enabled is True
    assert loaded.feishu.app_id == "cli_test"
    assert loaded.feishu.app_secret == "secret123"
    assert loaded.feishu.domain == "lark"
    assert loaded.feishu.group_policy.mode == "allowlist"
    assert loaded.feishu.group_policy.allowlist == ["oc_1"]


def test_save_creates_parent_dirs(tmp_path: Path):
    """保存时自动创建父目录。"""
    path = tmp_path / "nested" / "deep" / "channels.json"
    save_channels_config(ChannelsConfig(), path)
    assert path.exists()


def test_has_enabled_channels_and_names(tmp_path: Path):
    """has_enabled_channels / enabled_channel_names 反映启用状态。"""
    empty = ChannelsConfig()
    assert empty.has_enabled_channels() is False
    assert empty.enabled_channel_names() == []

    enabled = ChannelsConfig(feishu=FeishuChannelConfig(enabled=True, app_id="x"))
    assert enabled.has_enabled_channels() is True
    assert enabled.enabled_channel_names() == ["feishu"]
