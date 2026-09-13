"""渠道注册表测试

验证 ChannelRegistry 正确注册三个内置渠道，
并能按名称查询描述符。
"""
from __future__ import annotations

from illusion_forge.channels.registry import ChannelDescriptor, ChannelRegistry


def test_registry_has_three_channels():
    """注册表应包含 feishu/weixin/qq 三个内置渠道"""
    descriptors = ChannelRegistry.all_descriptors()
    names = {d.name for d in descriptors}
    assert names == {"feishu", "weixin", "qq"}


def test_registry_get_by_name():
    """按名称查询应返回正确的描述符"""
    desc = ChannelRegistry.get("feishu")
    assert desc is not None
    assert desc.name == "feishu"
    assert desc.config_attr == "feishu"
    assert "lark_oapi" in desc.dependencies


def test_registry_get_unknown_returns_none():
    """查询未知渠道名应返回 None"""
    assert ChannelRegistry.get("unknown") is None
    assert ChannelRegistry.get("") is None


def test_config_has_enabled_channels_uses_registry():
    """has_enabled_channels 遍历 registry 而非硬编码字段"""
    from illusion_forge.channels.config import ChannelsConfig, FeishuChannelConfig

    # 全部禁用
    empty = ChannelsConfig()
    assert empty.has_enabled_channels() is False

    # 仅飞书启用
    feishu_only = ChannelsConfig(feishu=FeishuChannelConfig(enabled=True, app_id="x"))
    assert feishu_only.has_enabled_channels() is True

    # 仅微信启用
    from illusion_forge.channels.config import WeixinChannelConfig
    weixin_only = ChannelsConfig(weixin=WeixinChannelConfig(enabled=True))
    assert weixin_only.has_enabled_channels() is True

    # 仅 QQ 启用
    from illusion_forge.channels.config import QQChannelConfig
    qq_only = ChannelsConfig(qq=QQChannelConfig(enabled=True))
    assert qq_only.has_enabled_channels() is True


def test_config_enabled_channel_names_uses_registry():
    """enabled_channel_names 遍历 registry 返回已启用渠道名"""
    from illusion_forge.channels.config import (
        ChannelsConfig,
        FeishuChannelConfig,
        QQChannelConfig,
        WeixinChannelConfig,
    )

    empty = ChannelsConfig()
    assert empty.enabled_channel_names() == []

    all_enabled = ChannelsConfig(
        feishu=FeishuChannelConfig(enabled=True, app_id="x"),
        weixin=WeixinChannelConfig(enabled=True),
        qq=QQChannelConfig(enabled=True),
    )
    names = set(all_enabled.enabled_channel_names())
    assert names == {"feishu", "weixin", "qq"}


def test_serve_dependency_check_uses_registry(monkeypatch):
    """serve.py 依赖检查应遍历 registry 的 dependencies 字段

    验证：当 feishu 启用但 lark_oapi 不可用时，
    依赖检查使用 registry 中注册的 dependencies。
    """
    import builtins

    # 模拟 lark_oapi 不可用
    real_import = builtins.__import__

    def _mock_import(name, *args, **kwargs):
        if name == "lark_oapi":
            raise ImportError("No module named 'lark_oapi'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _mock_import)

    from illusion_forge.channels import serve
    from illusion_forge.channels.config import ChannelsConfig, FeishuChannelConfig

    cfg = ChannelsConfig(feishu=FeishuChannelConfig(enabled=True, app_id="x"))

    # 捕获 print 输出
    import io
    from contextlib import redirect_stdout

    captured = io.StringIO()
    with redirect_stdout(captured):
        serve._check_channel_dependencies(cfg)

    output = captured.getvalue()
    # 应提示 feishu 依赖缺失
    assert "feishu" in output.lower() or "lark" in output.lower()


def test_config_fingerprint_uses_registry():
    """_config_fingerprint 遍历 registry 的 fingerprint_factory"""
    from illusion_forge.channels import _config_fingerprint
    from illusion_forge.channels.config import (
        ChannelsConfig,
        FeishuChannelConfig,
    )

    # 空配置：无启用渠道，指纹为空列表的 MD5
    empty = ChannelsConfig()
    fp_empty = _config_fingerprint(empty)

    # 启用飞书：指纹应变化
    feishu = ChannelsConfig(feishu=FeishuChannelConfig(enabled=True, app_id="cli_xxx"))
    fp_feishu = _config_fingerprint(feishu)
    assert fp_empty != fp_feishu

    # 不同 app_id：指纹应不同
    feishu2 = ChannelsConfig(feishu=FeishuChannelConfig(enabled=True, app_id="cli_yyy"))
    fp_feishu2 = _config_fingerprint(feishu2)
    assert fp_feishu != fp_feishu2

    # 相同配置：指纹应相同
    feishu_same = ChannelsConfig(feishu=FeishuChannelConfig(enabled=True, app_id="cli_xxx"))
    assert _config_fingerprint(feishu_same) == fp_feishu


def test_get_command_handler_uses_registry():
    """_get_command_handler 遍历 registry 的 command_handler_factory"""
    from unittest.mock import MagicMock

    from illusion_forge.channels import ChannelRunner

    # 用 mock channel 验证飞书路径
    from illusion_forge.channels.feishu.adapter import FeishuChannel
    mock_channel = MagicMock(spec=FeishuChannel)
    mock_session_store = MagicMock()

    runner = ChannelRunner.__new__(ChannelRunner)
    runner.channel = mock_channel
    runner.session_store = mock_session_store

    handler = runner._get_command_handler()
    assert handler is not None
    from illusion_forge.channels.feishu.commands import FeishuCommandHandler
    assert isinstance(handler, FeishuCommandHandler)


def test_create_session_store_uses_registry():
    """_create_session_store 遍历 registry 的 session_store_factory"""
    from pathlib import Path
    from unittest.mock import MagicMock

    from illusion_forge.channels import _create_session_store
    from illusion_forge.channels.feishu.adapter import FeishuChannel

    mock_channel = MagicMock(spec=FeishuChannel)
    store = _create_session_store(
        channel=mock_channel,
        data_dir=Path("/tmp/test"),
        group_sessions_per_user=True,
    )
    from illusion_forge.channels.feishu.session_map import FeishuSessionStore
    assert isinstance(store, FeishuSessionStore)


def test_registry_snapshot_restore_isolation():
    """snapshot/restore 应实现测试隔离

    注册 mock 渠道后用 restore 恢复，验证其他测试不受污染。
    """
    # 快照原始状态
    snap = ChannelRegistry.snapshot()
    original_names = {d.name for d in ChannelRegistry.all_descriptors()}

    try:
        # 注册一个 mock 渠道
        mock_desc = ChannelDescriptor(
            name="mock_test_channel",
            config_attr="mock",
            config_class=object,
            adapter_class=object,
            dependencies=(),
            session_store_factory=lambda *a: None,
            command_handler_factory=lambda *a: None,
            fingerprint_factory=lambda cfg: "mock",
        )
        ChannelRegistry.register(mock_desc)
        assert "mock_test_channel" in {d.name for d in ChannelRegistry.all_descriptors()}
    finally:
        # 恢复
        ChannelRegistry.restore(snap)

    # 恢复后 mock 渠道应消失
    restored_names = {d.name for d in ChannelRegistry.all_descriptors()}
    assert "mock_test_channel" not in restored_names
    assert restored_names == original_names


def test_descriptor_start_msg_fields():
    """ChannelDescriptor 的 start_msg_key 和 start_msg_needs_channel_name 字段"""
    feishu = ChannelRegistry.get("feishu")
    assert feishu is not None
    assert feishu.start_msg_key == "channel_starting"
    assert feishu.start_msg_needs_channel_name is True

    weixin = ChannelRegistry.get("weixin")
    assert weixin is not None
    assert weixin.start_msg_key == "channel_starting_weixin"
    assert weixin.start_msg_needs_channel_name is False

    qq = ChannelRegistry.get("qq")
    assert qq is not None
    assert qq.start_msg_key == "channel_starting_qq"
    assert qq.start_msg_needs_channel_name is False
