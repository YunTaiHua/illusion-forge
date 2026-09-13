# tests/channels/test_health_probe.py
"""渠道 health_probe 测试"""
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_default_health_probe_returns_true():
    """默认 health_probe 返回 True"""
    from illusion_forge.channels.base import Channel

    channel = MagicMock(spec=Channel)
    channel.health_probe = Channel.health_probe.__get__(channel, Channel)
    result = await channel.health_probe()
    assert result is True


@pytest.mark.asyncio
async def test_feishu_health_probe_success():
    """飞书 health_probe 成功（tenant_access_token API 返回 code=0）"""
    from illusion_forge.channels.config import FeishuChannelConfig
    from illusion_forge.channels.feishu.adapter import FeishuChannel

    cfg = FeishuChannelConfig(enabled=True, app_id="test_id", app_secret="test_secret")
    channel = FeishuChannel.__new__(FeishuChannel)
    channel.config = cfg
    channel._client = MagicMock()  # 只需非 None 即可

    # 模拟 urllib.request.urlopen 返回成功响应
    fake_resp_data = json.dumps({"code": 0, "tenant_access_token": "t-fake"}).encode()
    fake_http_resp = BytesIO(fake_resp_data)
    fake_http_resp.__enter__ = MagicMock(return_value=fake_http_resp)
    fake_http_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=fake_http_resp):
        result = await channel.health_probe()

    assert result is True


@pytest.mark.asyncio
async def test_feishu_health_probe_auth_failure():
    """飞书 health_probe 失败（API 返回 code!=0，如 app_secret 错误）"""
    from illusion_forge.channels.config import FeishuChannelConfig
    from illusion_forge.channels.feishu.adapter import FeishuChannel

    cfg = FeishuChannelConfig(enabled=True, app_id="test_id", app_secret="wrong_secret")
    channel = FeishuChannel.__new__(FeishuChannel)
    channel.config = cfg
    channel._client = MagicMock()

    # 模拟 API 返回 code=99991（认证失败）
    fake_resp_data = json.dumps({"code": 99991, "msg": "app_secret not match"}).encode()
    fake_http_resp = BytesIO(fake_resp_data)
    fake_http_resp.__enter__ = MagicMock(return_value=fake_http_resp)
    fake_http_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=fake_http_resp):
        result = await channel.health_probe()

    assert result is False


@pytest.mark.asyncio
async def test_feishu_health_probe_network_failure():
    """飞书 health_probe 失败（网络不可达，urlopen 抛异常）"""
    from illusion_forge.channels.config import FeishuChannelConfig
    from illusion_forge.channels.feishu.adapter import FeishuChannel

    cfg = FeishuChannelConfig(enabled=True, app_id="test_id", app_secret="test_secret")
    channel = FeishuChannel.__new__(FeishuChannel)
    channel.config = cfg
    channel._client = MagicMock()

    with patch("urllib.request.urlopen", side_effect=ConnectionError("网络不可达")):
        result = await channel.health_probe()

    assert result is False


@pytest.mark.asyncio
async def test_feishu_health_probe_no_client():
    """飞书 health_probe 在 _client 为 None 时返回 False"""
    from illusion_forge.channels.config import FeishuChannelConfig
    from illusion_forge.channels.feishu.adapter import FeishuChannel

    cfg = FeishuChannelConfig(enabled=True, app_id="test_id", app_secret="test_secret")
    channel = FeishuChannel.__new__(FeishuChannel)
    channel.config = cfg
    channel._client = None

    result = await channel.health_probe()
    assert result is False
