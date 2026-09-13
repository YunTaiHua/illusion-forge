"""投递解析测试"""
from __future__ import annotations

try:
    import aiohttp  # noqa: F401
    _has_aiohttp = True
except ImportError:
    _has_aiohttp = False

try:
    import lark_oapi  # noqa: F401
    _has_lark_oapi = True
except ImportError:
    _has_lark_oapi = False

from illusion_forge.channels.delivery import parse_deliver_targets


def test_parse_empty_list():
    """空列表返回空"""
    assert parse_deliver_targets([]) == []


def test_parse_channel_with_chat_id():
    """渠道名:chat_id 格式（显式 chat_id 优先级最高）"""
    assert parse_deliver_targets(["feishu:oc_456"]) == [("feishu", "oc_456", "")]


def test_parse_qq_format():
    """QQ 渠道格式"""
    assert parse_deliver_targets(["qq:group_123"]) == [("qq", "group_123", "")]


def test_parse_weixin_format():
    """微信渠道格式"""
    assert parse_deliver_targets(["weixin:wxid_abc"]) == [("weixin", "wxid_abc", "")]


def test_parse_feishu_open_id():
    """飞书用户 open_id 格式"""
    assert parse_deliver_targets(["feishu:ou_xxx"]) == [("feishu", "ou_xxx", "")]


def test_parse_invalid_format():
    """deliver_to 项含冒号但缺 channel 或 chat_id → 跳过"""
    assert parse_deliver_targets(["feishu:"]) == []
    assert parse_deliver_targets([":oc_123"]) == []


def test_parse_channel_only_with_chat_id():
    """仅渠道名 + chat_id 有值 → 用 chat_id 回投来源会话"""
    assert parse_deliver_targets(["feishu"], chat_id="oc_origin") == [("feishu", "oc_origin", "")]


def test_parse_channel_only_without_chat_id():
    """仅渠道名 + chat_id 为空 → 跳过（LLM 应填完整 ID）"""
    assert parse_deliver_targets(["feishu"]) == []


def test_parse_channel_only_with_empty_chat_id():
    """仅渠道名 + chat_id 空串 → 跳过"""
    assert parse_deliver_targets(["qq"], chat_id="") == []


def test_parse_explicit_chat_id_overrides_origin():
    """显式 chat_id（含冒号）优先于 origin chat_id"""
    assert parse_deliver_targets(["feishu:oc_explicit"], chat_id="oc_origin") == [("feishu", "oc_explicit", "")]


def test_parse_unknown_channel_with_chat_id():
    """未知渠道名 + chat_id → 仍返回（渠道名校验在 deliver_to_channel 中）"""
    assert parse_deliver_targets(["unknown:xxx"]) == [("unknown", "xxx", "")]


def test_parse_unknown_channel_without_chat_id():
    """未知渠道名 + 无 chat_id → 跳过"""
    assert parse_deliver_targets(["unknown"]) == []


def test_parse_strips_whitespace_around_channel_and_chat_id():
    """LLM 输出常在冒号后带空格，应 strip 两端空白"""
    assert parse_deliver_targets(["feishu: oc_456"]) == [("feishu", "oc_456", "")]
    assert parse_deliver_targets([" feishu : ou_xxx "]) == [("feishu", "ou_xxx", "")]
    assert parse_deliver_targets(["qq:  group_123"]) == [("qq", "group_123", "")]


def test_parse_multiple_targets():
    """多目标广播：每个目标独立解析"""
    assert parse_deliver_targets(["feishu:oc_1", "weixin:wxid1", "qq:openid1"]) == [
        ("feishu", "oc_1", ""),
        ("weixin", "wxid1", ""),
        ("qq", "openid1", ""),
    ]


def test_parse_partial_invalid_skipped():
    """部分无效项跳过，不影响其他有效项"""
    assert parse_deliver_targets(["feishu:oc_1", "", "invalid:", "qq:openid1"]) == [
        ("feishu", "oc_1", ""),
        ("qq", "openid1", ""),
    ]


def test_parse_non_string_items_skipped():
    """非字符串项跳过"""
    assert parse_deliver_targets(["feishu:oc_1", 123, None, "qq:openid1"]) == [  # type: ignore[list-item]
        ("feishu", "oc_1", ""),
        ("qq", "openid1", ""),
    ]


def test_parse_mixed_explicit_and_origin_chat_id():
    """混合：显式 chat_id + 仅渠道名（用 origin chat_id 回退）"""
    result = parse_deliver_targets(["feishu:oc_explicit", "weixin"], chat_id="wxid_origin")
    assert result == [("feishu", "oc_explicit", ""), ("weixin", "wxid_origin", "")]


# ── 测试 deliver_file_to_channel ──────────────────────────────
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from illusion_forge.channels.config import (
    ChannelsConfig,
    FeishuChannelConfig,
    QQChannelConfig,
    WeixinChannelConfig,
)
from illusion_forge.channels.delivery import deliver_file_to_channel


@pytest.mark.skipif(not _has_lark_oapi, reason="lark_oapi not installed")
@pytest.mark.asyncio
async def test_deliver_file_feishu_success(tmp_path: Path) -> None:
    file_path = tmp_path / "test.txt"
    file_path.write_text("hello", encoding="utf-8")
    cfg = ChannelsConfig(
        feishu=FeishuChannelConfig(enabled=True, app_id="x", app_secret="y"),
    )
    # 构造 mock lark client：im.v1.file.create + im.v1.message.create 都返回成功
    mock_file_resp = MagicMock()
    mock_file_resp.success.return_value = True
    mock_file_resp.data.file_key = "file_key_abc"

    mock_msg_resp = MagicMock()
    mock_msg_resp.success.return_value = True

    mock_client = MagicMock()
    mock_client.im.v1.file.create = MagicMock(return_value=mock_file_resp)
    mock_client.im.v1.message.create = MagicMock(return_value=mock_msg_resp)

    with patch("illusion_forge.channels.feishu.messaging.build_lark_client", return_value=mock_client), \
         patch("illusion_forge.channels.feishu.messaging.resolve_receive_id", return_value=("ou_user1", "open_id")):
        result = await deliver_file_to_channel(
            "feishu", "ou_user1", str(file_path), config=cfg, caption="hi",
        )
    assert result is True
    mock_client.im.v1.file.create.assert_called_once()
    # caption 非空时：先发文本消息，再发文件消息 → message.create 调用 2 次
    assert mock_client.im.v1.message.create.call_count == 2


@pytest.mark.skipif(not _has_aiohttp, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_deliver_file_qq_success(tmp_path: Path) -> None:
    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")
    cfg = ChannelsConfig(
        qq=QQChannelConfig(enabled=True, app_id="x", client_secret="y"),
    )
    with patch("illusion_forge.channels.qq.api.ensure_token", new_callable=AsyncMock) as mock_token, \
         patch("illusion_forge.channels.qq.api.upload_file", new_callable=AsyncMock) as mock_upload, \
         patch("illusion_forge.channels.qq.api.send_media_message", new_callable=AsyncMock) as mock_media:
        mock_token.return_value = "tok"
        mock_upload.return_value = {"file_info": "file_info_abc"}
        mock_media.return_value = "msg_id_123"
        result = await deliver_file_to_channel(
            "qq", "openid_group1", str(file_path), config=cfg,
        )
    assert result is True
    mock_upload.assert_awaited_once()
    mock_media.assert_awaited_once()


@pytest.mark.skipif(not _has_aiohttp, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_deliver_file_weixin_success(tmp_path: Path) -> None:
    file_path = tmp_path / "img.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n fake")
    cfg = ChannelsConfig(
        weixin=WeixinChannelConfig(enabled=True, account_id="bot@im.bot", token="tok"),
    )
    with patch("illusion_forge.channels.weixin.ilink_api.get_upload_url", new_callable=AsyncMock) as mock_get_url, \
         patch("illusion_forge.channels.weixin.ilink_api.upload_ciphertext", new_callable=AsyncMock) as mock_upload, \
         patch("illusion_forge.channels.weixin.ilink_api._api_post", new_callable=AsyncMock) as mock_post, \
         patch("illusion_forge.channels.weixin.ilink_api._make_ssl_connector", return_value=None), \
         patch("illusion_forge.channels.weixin.ilink_api.send_message", new_callable=AsyncMock) as mock_send, \
         patch("illusion_forge.channels.delivery._load_weixin_context_token", return_value="valid_context_token"):
        mock_get_url.return_value = {"upload_full_url": "https://cdn.example.com/upload"}
        mock_upload.return_value = "encrypted_param"
        mock_post.return_value = {"errcode": 0}
        result = await deliver_file_to_channel(
            "weixin", "wxid_user1", str(file_path), config=cfg, caption="cap",
        )
    assert result is True
    mock_get_url.assert_awaited_once()
    mock_upload.assert_awaited_once()
    mock_post.assert_awaited_once()
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_deliver_file_channel_not_enabled(tmp_path: Path) -> None:
    file_path = tmp_path / "x.txt"
    file_path.write_text("x", encoding="utf-8")
    cfg = ChannelsConfig()
    result = await deliver_file_to_channel("feishu", "ou_x", str(file_path), config=cfg)
    assert result is False


@pytest.mark.asyncio
async def test_deliver_file_file_not_found() -> None:
    cfg = ChannelsConfig(
        feishu=FeishuChannelConfig(enabled=True, app_id="x", app_secret="y"),
    )
    result = await deliver_file_to_channel(
        "feishu", "ou_x", "/nonexistent/file.txt", config=cfg,
    )
    assert result is False


@pytest.mark.asyncio
async def test_deliver_file_unknown_channel(tmp_path: Path) -> None:
    file_path = tmp_path / "x.txt"
    file_path.write_text("x", encoding="utf-8")
    cfg = ChannelsConfig()
    result = await deliver_file_to_channel("unknown", "x", str(file_path), config=cfg)
    assert result is False
