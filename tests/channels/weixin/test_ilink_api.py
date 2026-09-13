"""iLink Bot API 客户端测试（纯逻辑，不依赖 aiohttp）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

try:
    import aiohttp  # noqa: F401
    _has_aiohttp = True
except ImportError:
    _has_aiohttp = False

from illusion_forge.channels.weixin.ilink_api import (
    ILINK_APP_CLIENT_VERSION,
    MAX_MESSAGE_LENGTH,
    MSG_STATE_FINISH,
    MSG_TYPE_BOT,
    TYPING_START,
    TYPING_STOP,
    WeixinCredentials,
    _build_headers,
    _split_text,
    qr_login_with_browser,
)


def test_build_headers_has_auth():
    """请求头包含 Bearer token 和 iLink 标识。"""
    headers = _build_headers(token="test_token_123")
    assert headers["Authorization"] == "Bearer test_token_123"
    assert headers["iLink-App-Id"] == "bot"
    assert headers["iLink-App-ClientVersion"] == str(ILINK_APP_CLIENT_VERSION)
    assert "X-WECHAT-UIN" in headers


def test_build_headers_random_uin():
    """每次调用 X-WECHAT-UIN 不同。"""
    h1 = _build_headers(token="t")
    h2 = _build_headers(token="t")
    assert h1["X-WECHAT-UIN"] != h2["X-WECHAT-UIN"]


def test_split_text_short():
    """短文本不分片。"""
    assert _split_text("hello", 2000) == ["hello"]


def test_split_text_long():
    """长文本按段落分片。"""
    para = "a" * 1500
    text = f"{para}\n\n{para}"
    chunks = _split_text(text, 2000)
    assert len(chunks) == 2
    assert all(len(c) <= 2000 for c in chunks)


def test_split_text_preserves_paragraphs():
    """分片不在段落中间断。"""
    para1 = "b" * 1900
    para2 = "c" * 100
    text = f"{para1}\n\n{para2}"
    chunks = _split_text(text, 2000)
    assert len(chunks) == 2
    assert para1 in chunks[0]
    assert para2 in chunks[1]


def test_weixin_credentials_dataclass():
    """凭据数据类正确构造。"""
    creds = WeixinCredentials(
        account_id="bot@im.bot",
        token="tok",
        base_url="https://ilinkai.weixin.qq.com",
        user_id="u123",
    )
    assert creds.account_id == "bot@im.bot"
    assert creds.token == "tok"
    assert creds.base_url == "https://ilinkai.weixin.qq.com"
    assert creds.user_id == "u123"


def test_constants_correct():
    """核心常量值正确。"""
    assert MAX_MESSAGE_LENGTH == 2000
    assert MSG_TYPE_BOT == 2
    assert MSG_STATE_FINISH == 2
    assert TYPING_START == 1
    assert TYPING_STOP == 2
    assert ILINK_APP_CLIENT_VERSION == (2 << 16) | (2 << 8) | 0


@pytest.mark.skipif(not _has_aiohttp, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_qr_login_uses_status_field():
    """扫码轮询必须检查 status 字段（非 ret），并正确处理 confirmed 状态。"""
    # 模拟 API 响应序列：wait → scaned → confirmed
    qr_response = {"qrcode": "abc123", "qrcode_img_content": "https://example.com/qr"}
    status_sequence = [
        {"status": "wait"},
        {"status": "scaned"},
        {
            "status": "confirmed",
            "ilink_bot_id": "bot@im.bot",
            "bot_token": "tok_xyz",
            "baseurl": "https://ilinkai.weixin.qq.com",
            "ilink_user_id": "u123",
        },
    ]
    status_iter = iter(status_sequence)

    with (
        patch(
            "illusion_forge.channels.weixin.ilink_api.get_bot_qrcode",
            new_callable=AsyncMock,
            return_value=qr_response,
        ),
        patch(
            "illusion_forge.channels.weixin.ilink_api.get_qrcode_status",
            new_callable=AsyncMock,
            side_effect=lambda *a, **kw: next(status_iter),
        ),
        patch(
            "illusion_forge.channels.weixin.ilink_api._serve_qr_in_browser",
            return_value={"server": type("S", (), {"shutdown": lambda self: None})(), "port": 0, "state": {}},
        ),
    ):
        creds = await qr_login_with_browser()

    assert creds is not None
    assert creds.account_id == "bot@im.bot"
    assert creds.token == "tok_xyz"
    assert creds.user_id == "u123"


@pytest.mark.skipif(not _has_aiohttp, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_qr_login_expires_and_refreshes():
    """二维码过期后应自动刷新，而非永久等待。"""
    qr_response = {"qrcode": "abc123", "qrcode_img_content": "https://example.com/qr"}
    refreshed_qr = {"qrcode": "def456", "qrcode_img_content": "https://example.com/qr2"}
    status_sequence = [
        {"status": "expired"},
        {
            "status": "confirmed",
            "ilink_bot_id": "bot@im.bot",
            "bot_token": "tok",
            "baseurl": "https://ilinkai.weixin.qq.com",
            "ilink_user_id": "u1",
        },
    ]
    status_iter = iter(status_sequence)
    call_count = 0

    async def mock_get_qr(session, *, base_url):
        nonlocal call_count
        call_count += 1
        return qr_response if call_count == 1 else refreshed_qr

    with (
        patch(
            "illusion_forge.channels.weixin.ilink_api.get_bot_qrcode",
            new_callable=AsyncMock,
            side_effect=mock_get_qr,
        ),
        patch(
            "illusion_forge.channels.weixin.ilink_api.get_qrcode_status",
            new_callable=AsyncMock,
            side_effect=lambda *a, **kw: next(status_iter),
        ),
        patch(
            "illusion_forge.channels.weixin.ilink_api._serve_qr_in_browser",
            return_value={"server": type("S", (), {"shutdown": lambda self: None})(), "port": 0, "state": {}},
        ),
        patch(
            "illusion_forge.channels.weixin.ilink_api._refresh_qr_server",
        ),
    ):
        creds = await qr_login_with_browser()

    assert creds is not None
    assert creds.token == "tok"
    assert call_count == 2  # 首次 + 过期后刷新
