"""微信适配器准入控制与媒体收发测试。"""
from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from illusion_forge.channels.base import Attachment, InboundMessage
from illusion_forge.channels.config import WeixinChannelConfig
from illusion_forge.channels.weixin.adapter import WeixinChannel


def _channel(allow_bots=False, bot_user_id="self_bot"):
    """构造 WeixinChannel 实例（仅测准入逻辑，不连接）。"""
    cfg = WeixinChannelConfig(enabled=True, allow_bots=allow_bots, account_id=bot_user_id, user_id=bot_user_id)
    ch = WeixinChannel.__new__(WeixinChannel)  # 跳过 __init__ 避免连接
    ch.config = cfg
    ch._account_id = bot_user_id
    ch._context_tokens = {}
    ch._aes_key_cache = {}  # 附件 AES 密钥缓存
    ch._send_session = None
    ch._poll_session = None
    return ch


def _msg(user_id="wx_user", chat_type="dm", is_bot=False):
    """构造入站消息。"""
    return InboundMessage(
        text="hi", chat_id=user_id, chat_type=chat_type,
        user_id=user_id, user_name="u", message_id="om_1", is_bot=is_bot,
    )


def test_admit_self_echo_rejected():
    """自回显被拒。"""
    ch = _channel(bot_user_id="self_bot")
    assert ch._admit(_msg(user_id="self_bot")) is False


def test_admit_other_bot_rejected():
    """allow_bots=False 时其他机器人被拒。"""
    ch = _channel(allow_bots=False)
    assert ch._admit(_msg(user_id="other_bot", is_bot=True)) is False


def test_admit_dm_allowed():
    """私聊放行。"""
    ch = _channel()
    assert ch._admit(_msg(user_id="wx_user", chat_type="dm")) is True


def test_admit_group_rejected():
    """群消息直接丢弃（bot 身份限制）。"""
    ch = _channel()
    assert ch._admit(_msg(user_id="wx_user", chat_type="group")) is False


def test_admit_bot_allowed_when_enabled():
    """allow_bots=True 时机器人放行。"""
    ch = _channel(allow_bots=True)
    assert ch._admit(_msg(user_id="other_bot", is_bot=True)) is True


def test_normalize_extracts_context_token():
    """_normalize 从入站消息提取 context_token 并缓存。"""
    ch = _channel()
    raw_msg = {
        "from_user_id": "wx_user",
        "context_token": "ctx_tok_123",
        "item_list": [{"type": 1, "text_item": {"text": "你好"}}],
        "msgid": "msg_001",
    }
    msg = ch._normalize(raw_msg)
    assert msg is not None
    assert msg.text == "你好"
    assert msg.user_id == "wx_user"
    assert ch._context_tokens.get("wx_user") == "ctx_tok_123"


def test_normalize_returns_none_for_empty_user():
    """from_user_id 为空时返回 None。"""
    ch = _channel()
    msg = ch._normalize({"from_user_id": "", "item_list": []})
    assert msg is None


def test_normalize_extracts_text_from_item_list():
    """从 item_list 的 type=1 项提取文本。"""
    ch = _channel()
    raw_msg = {
        "from_user_id": "wx_user",
        "item_list": [
            {"type": 99, "text_item": {"text": "ignored"}},
            {"type": 1, "text_item": {"text": "实际文本"}},
        ],
        "msgid": "msg_002",
    }
    msg = ch._normalize(raw_msg)
    assert msg is not None
    assert msg.text == "实际文本"


# ─── 附件解析测试 ──────────────────────────────────────────────


def test_normalize_extracts_image_attachment():
    """_normalize 从 image_item 提取附件元数据并缓存 AES 密钥。"""
    ch = _channel()
    raw_msg = {
        "from_user_id": "wx_user",
        "msgid": "msg_img_1",
        "item_list": [
            {"type": 1, "text_item": {"text": "看这张图"}},
            {
                "type": 2,  # ITEM_IMAGE
                "image_item": {
                    "media": {
                        "encrypt_query_param": "enc_param_abc",
                        "aes_key": base64.b64encode(b"0" * 16).decode(),
                        "full_url": "https://novac2c.cdn.weixin.qq.com/c2c/full",
                    },
                    "mid_size": 2048,
                },
            },
        ],
    }
    msg = ch._normalize(raw_msg)
    assert msg is not None
    assert len(msg.attachments) == 1
    att = msg.attachments[0]
    assert att.media_type == "image"
    assert att.file_key == "enc_param_abc"
    assert att.download_url == "https://novac2c.cdn.weixin.qq.com/c2c/full"
    assert att.size == 2048
    # AES 密钥缓存
    assert "msg_img_1:1" in ch._aes_key_cache


def test_normalize_image_legacy_aeskey_hex_field():
    """image_item 的旧字段 aeskey（hex）应转换为 base64(hex_string)。"""
    ch = _channel()
    aeskey_hex = "00112233445566778899aabbccddeeff"
    raw_msg = {
        "from_user_id": "wx_user",
        "msgid": "msg_img_legacy",
        "item_list": [
            {
                "type": 2,
                "image_item": {
                    "aeskey": aeskey_hex,  # 旧字段
                    "media": {"encrypt_query_param": "enc_param_legacy"},
                },
            },
        ],
    }
    msg = ch._normalize(raw_msg)
    assert msg is not None
    assert len(msg.attachments) == 1
    # 缓存的 aes_key 应为 base64(hex_string)
    cached = ch._aes_key_cache.get("msg_img_legacy:1")
    assert cached is not None
    expected = base64.b64encode(aeskey_hex.encode("ascii")).decode("ascii")
    assert cached[0] == expected


def test_normalize_extracts_file_attachment_with_filename():
    """file_item 保留原始文件名。"""
    ch = _channel()
    raw_msg = {
        "from_user_id": "wx_user",
        "msgid": "msg_file_1",
        "item_list": [
            {
                "type": 4,  # ITEM_FILE
                "file_item": {
                    "file_name": "report.pdf",
                    "len": "65536",
                    "media": {
                        "encrypt_query_param": "file_enc_param",
                        "aes_key": base64.b64encode(b"k" * 16).decode(),
                    },
                },
            },
        ],
    }
    msg = ch._normalize(raw_msg)
    assert msg is not None
    assert len(msg.attachments) == 1
    att = msg.attachments[0]
    assert att.media_type == "file"
    assert att.filename == "report.pdf"
    assert att.size == 65536
    assert att.file_key == "file_enc_param"


def test_normalize_extracts_video_attachment():
    """video_item 解析。"""
    ch = _channel()
    raw_msg = {
        "from_user_id": "wx_user",
        "msgid": "msg_video_1",
        "item_list": [
            {
                "type": 5,  # ITEM_VIDEO
                "video_item": {
                    "video_size": 102400,
                    "media": {
                        "encrypt_query_param": "video_enc",
                        "aes_key": base64.b64encode(b"v" * 16).decode(),
                    },
                },
            },
        ],
    }
    msg = ch._normalize(raw_msg)
    assert msg is not None
    assert len(msg.attachments) == 1
    att = msg.attachments[0]
    assert att.media_type == "video"
    assert att.size == 102400


def test_normalize_voice_with_transcript_skipped():
    """voice_item 有转录文本时不生成附件（文本已通过 text_item 提取）。"""
    ch = _channel()
    raw_msg = {
        "from_user_id": "wx_user",
        "msgid": "msg_voice_1",
        "item_list": [
            {
                "type": 3,  # ITEM_VOICE
                "voice_item": {
                    "text": "这是转录文本",
                    "media": {"encrypt_query_param": "voice_enc"},
                },
            },
        ],
    }
    msg = ch._normalize(raw_msg)
    assert msg is not None
    assert len(msg.attachments) == 0


def test_normalize_voice_without_transcript_extracted():
    """voice_item 无转录文本时生成音频附件。"""
    ch = _channel()
    raw_msg = {
        "from_user_id": "wx_user",
        "msgid": "msg_voice_2",
        "item_list": [
            {
                "type": 3,
                "voice_item": {
                    "media": {"encrypt_query_param": "voice_enc"},
                },
            },
        ],
    }
    msg = ch._normalize(raw_msg)
    assert msg is not None
    assert len(msg.attachments) == 1
    assert msg.attachments[0].media_type == "audio"


def test_normalize_skips_item_without_credentials():
    """无 encrypt_query_param 且无 full_url 的 item 被跳过。"""
    ch = _channel()
    raw_msg = {
        "from_user_id": "wx_user",
        "msgid": "msg_empty",
        "item_list": [
            {
                "type": 2,
                "image_item": {"media": {}},  # 无下载凭证
            },
        ],
    }
    msg = ch._normalize(raw_msg)
    assert msg is not None
    assert len(msg.attachments) == 0


# ─── AES 加解密测试 ─────────────────────────────────────────────


def test_aes128_ecb_encrypt_decrypt_roundtrip():
    """AES-128-ECB 加解密往返。"""
    from illusion_forge.channels.weixin.ilink_api import (
        _aes128_ecb_decrypt,
        _aes128_ecb_encrypt,
    )

    key = b"0123456789abcdef"
    plaintext = b"hello weixin media encryption" * 3
    ciphertext = _aes128_ecb_encrypt(plaintext, key)
    # 密文长度是 16 的倍数（PKCS#7 填充）
    assert len(ciphertext) % 16 == 0
    assert ciphertext != plaintext
    decrypted = _aes128_ecb_decrypt(ciphertext, key)
    assert decrypted == plaintext


def test_aes_padded_size_calculation():
    """_aes_padded_size 正确计算填充后密文长度。"""
    from illusion_forge.channels.weixin.ilink_api import _aes_padded_size

    # 0 字节 → 16（全填充）
    assert _aes_padded_size(0) == 16
    # 15 字节 → 16
    assert _aes_padded_size(15) == 16
    # 16 字节 → 32（额外一个完整填充块）
    assert _aes_padded_size(16) == 32
    # 100 字节 → 112（7 个块）
    assert _aes_padded_size(100) == 112


def test_parse_aes_key_raw_16_bytes():
    """_parse_aes_key 支持 base64(16 字节原始密钥)。"""
    from illusion_forge.channels.weixin.ilink_api import _parse_aes_key

    raw_key = b"0123456789abcdef"
    b64 = base64.b64encode(raw_key).decode()
    parsed = _parse_aes_key(b64)
    assert parsed == raw_key


def test_parse_aes_key_hex_string_format():
    """_parse_aes_key 支持 base64(hex_string) 格式（iLink 标准）。"""
    from illusion_forge.channels.weixin.ilink_api import _parse_aes_key

    raw_key = b"0123456789abcdef"
    hex_str = raw_key.hex()  # 32 字符 hex
    b64 = base64.b64encode(hex_str.encode("ascii")).decode()
    parsed = _parse_aes_key(b64)
    assert parsed == raw_key


def test_parse_aes_key_invalid_format_raises():
    """无效 AES 密钥格式抛出 ValueError。"""
    from illusion_forge.channels.weixin.ilink_api import _parse_aes_key

    # 8 字节不符合任何格式
    b64 = base64.b64encode(b"8bytes!!").decode()
    with pytest.raises(ValueError):
        _parse_aes_key(b64)


# ─── CDN URL 构造与 SSRF 防护 ─────────────────────────────────


def test_cdn_download_url_construction():
    """_cdn_download_url 正确构造下载 URL。"""
    from illusion_forge.channels.weixin.ilink_api import _cdn_download_url

    url = _cdn_download_url("https://novac2c.cdn.weixin.qq.com/c2c", "abc def&param")
    # 特殊字符应被 URL 编码
    assert "encrypted_query_param=abc%20def%26param" in url
    assert url.startswith("https://novac2c.cdn.weixin.qq.com/c2c/download?")


def test_cdn_upload_url_construction():
    """_cdn_upload_url 正确构造上传 URL。"""
    from illusion_forge.channels.weixin.ilink_api import _cdn_upload_url

    url = _cdn_upload_url("https://novac2c.cdn.weixin.qq.com/c2c/", "upload_param", "filekey_123")
    assert url == (
        "https://novac2c.cdn.weixin.qq.com/c2c/upload"
        "?encrypted_query_param=upload_param&filekey=filekey_123"
    )


def test_assert_weixin_cdn_url_allows_whitelisted_host():
    """_assert_weixin_cdn_url 放行白名单主机。"""
    from illusion_forge.channels.weixin.ilink_api import _assert_weixin_cdn_url

    # 不抛异常即通过
    _assert_weixin_cdn_url("https://novac2c.cdn.weixin.qq.com/c2c/download?x=1")
    _assert_weixin_cdn_url("https://ilinkai.weixin.qq.com/path")


def test_assert_weixin_cdn_url_rejects_unknown_host():
    """_assert_weixin_cdn_url 拒绝非白名单主机（SSRF 防护）。"""
    from illusion_forge.channels.weixin.ilink_api import _assert_weixin_cdn_url

    with pytest.raises(ValueError, match="allowlist"):
        _assert_weixin_cdn_url("https://evil.example.com/download")


def test_assert_weixin_cdn_url_rejects_non_http_scheme():
    """_assert_weixin_cdn_url 拒绝非 http/https 协议。"""
    from illusion_forge.channels.weixin.ilink_api import _assert_weixin_cdn_url

    with pytest.raises(ValueError, match="scheme"):
        _assert_weixin_cdn_url("file:///etc/passwd")


# ─── _outbound_media_builder 测试 ───────────────────────────────


def test_outbound_media_builder_image(tmp_path):
    """图片 MIME 路由到 ITEM_IMAGE。"""
    ch = _channel()
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake jpg")
    media_type, builder = ch._outbound_media_builder(str(img_path))
    from illusion_forge.channels.weixin.ilink_api import ITEM_IMAGE, MEDIA_IMAGE
    assert media_type == MEDIA_IMAGE
    item = builder(
        encrypt_query_param="enc", aes_key_for_api="aes",
        ciphertext_size=128, plaintext_size=100,
        filename="test.jpg", rawfilemd5="md5",
    )
    assert item["type"] == ITEM_IMAGE
    assert item["image_item"]["media"]["encrypt_query_param"] == "enc"
    assert item["image_item"]["media"]["aes_key"] == "aes"
    assert item["image_item"]["mid_size"] == 128


def test_outbound_media_builder_video(tmp_path):
    """视频 MIME 路由到 ITEM_VIDEO。"""
    ch = _channel()
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake mp4")
    media_type, builder = ch._outbound_media_builder(str(video_path))
    from illusion_forge.channels.weixin.ilink_api import ITEM_VIDEO, MEDIA_VIDEO
    assert media_type == MEDIA_VIDEO
    item = builder(
        encrypt_query_param="enc", aes_key_for_api="aes",
        ciphertext_size=1024, plaintext_size=900,
        filename="clip.mp4", rawfilemd5="md5",
    )
    assert item["type"] == ITEM_VIDEO
    assert item["video_item"]["video_size"] == 1024
    assert item["video_item"]["video_md5"] == "md5"


def test_outbound_media_builder_file_default(tmp_path):
    """非图片/视频 MIME 默认路由到 ITEM_FILE。"""
    ch = _channel()
    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"fake pdf")
    media_type, builder = ch._outbound_media_builder(str(file_path))
    from illusion_forge.channels.weixin.ilink_api import ITEM_FILE, MEDIA_FILE
    assert media_type == MEDIA_FILE
    item = builder(
        encrypt_query_param="enc", aes_key_for_api="aes",
        ciphertext_size=512, plaintext_size=400,
        filename="doc.pdf", rawfilemd5="md5",
    )
    assert item["type"] == ITEM_FILE
    assert item["file_item"]["file_name"] == "doc.pdf"
    assert item["file_item"]["len"] == "400"


def test_outbound_media_builder_force_file_attachment(tmp_path):
    """force_file_attachment=True 时图片也走文件通道。"""
    ch = _channel()
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(b"fake png")
    media_type, _ = ch._outbound_media_builder(str(img_path), force_file_attachment=True)
    from illusion_forge.channels.weixin.ilink_api import MEDIA_FILE
    assert media_type == MEDIA_FILE


# ─── download_attachment 测试 ──────────────────────────────────


@pytest.mark.asyncio
async def test_download_attachment_decrypts_with_cached_aes_key(tmp_path):
    """download_attachment 从缓存取 AES 密钥，下载并解密。"""
    ch = _channel()
    # 准备缓存
    raw_key = b"0123456789abcdef"
    aes_key_b64 = base64.b64encode(raw_key).decode()
    msg_id, att_id = "msg_1", "1"
    ch._aes_key_cache[f"{msg_id}:{att_id}"] = (aes_key_b64, float("inf"))

    # 准备附件（携带 message_id 以精确查找 AES 密钥缓存）
    att = Attachment(
        id=att_id, media_type="image", filename="img.jpg",
        size=100, file_key="enc_param", download_url="",
        message_id=msg_id,
    )

    # 模拟明文
    plaintext = b"image content here"

    # download_and_decrypt_media 在 adapter 内延迟导入，
    # 直接替换 ilink_api 模块属性
    from illusion_forge.channels.weixin import ilink_api

    async def fake_download(session, *, cdn_base_url, encrypted_query_param,
                            aes_key_b64, full_url, timeout_seconds=60):
        assert encrypted_query_param == "enc_param"
        assert aes_key_b64 == base64.b64encode(raw_key).decode()
        return plaintext

    ch._poll_session = MagicMock()
    save_path = tmp_path / "out" / "img.jpg"

    original = ilink_api.download_and_decrypt_media
    ilink_api.download_and_decrypt_media = fake_download
    try:
        result = await ch.download_attachment(att, str(save_path))
    finally:
        ilink_api.download_and_decrypt_media = original

    assert result == str(save_path)
    assert save_path.exists()
    assert save_path.read_bytes() == plaintext


@pytest.mark.asyncio
async def test_download_attachment_uses_correct_aes_key_across_messages(tmp_path):
    """回归测试：两条消息各自带附件 1，下载第二条附件时必须用第二条的密钥。

    防止 C1 回归：旧实现用 endswith(':1') 跨消息匹配，会命中最早消息的密钥。
    """
    ch = _channel()
    # 两条消息，各自的附件 ID 都是 "1"，但 AES 密钥不同
    key_a = base64.b64encode(b"0123456789abcdef").decode()  # msg_a 的密钥
    key_b = base64.b64encode(b"fedcba9876543210").decode()  # msg_b 的密钥
    ch._aes_key_cache["msg_a:1"] = (key_a, float("inf"))
    ch._aes_key_cache["msg_b:1"] = (key_b, float("inf"))

    # 下载 msg_b 的附件，应使用 key_b
    att = Attachment(
        id="1", media_type="image", filename="img.jpg",
        size=100, file_key="enc_param", download_url="",
        message_id="msg_b",
    )

    from illusion_forge.channels.weixin import ilink_api

    captured_key = []

    async def fake_download(session, *, cdn_base_url, encrypted_query_param,
                            aes_key_b64, full_url, timeout_seconds=60):
        captured_key.append(aes_key_b64)
        return b"image content"

    ch._poll_session = MagicMock()
    save_path = tmp_path / "out" / "img.jpg"

    original = ilink_api.download_and_decrypt_media
    ilink_api.download_and_decrypt_media = fake_download
    try:
        await ch.download_attachment(att, str(save_path))
    finally:
        ilink_api.download_and_decrypt_media = original

    # 必须用 msg_b 的密钥，不是 msg_a 的
    assert captured_key == [key_b], f"应使用 msg_b 的密钥 {key_b}，实际用了 {captured_key}"


@pytest.mark.asyncio
async def test_download_attachment_raises_without_crypto(monkeypatch, tmp_path):
    """cryptography 未安装时 download_attachment 抛 NotImplementedError。"""
    ch = _channel()
    att = Attachment(
        id="1", media_type="file", filename="doc.pdf",
        size=100, file_key="enc", download_url="",
    )

    from illusion_forge.channels.weixin import ilink_api
    monkeypatch.setattr(ilink_api, "_check_crypto_available", lambda: False)

    with pytest.raises(NotImplementedError, match="cryptography"):
        await ch.download_attachment(att, str(tmp_path / "doc.pdf"))


@pytest.mark.asyncio
async def test_download_attachment_raises_without_credentials(tmp_path):
    """附件无 file_key 且无 download_url 时抛 RuntimeError。"""
    ch = _channel()
    att = Attachment(
        id="1", media_type="file", filename="doc.pdf",
        size=100, file_key="", download_url="",
    )
    ch._poll_session = MagicMock()
    with pytest.raises(RuntimeError, match="无下载凭证"):
        await ch.download_attachment(att, str(tmp_path / "doc.pdf"))


# ─── _send_file 流程测试 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_send_image_full_flow(tmp_path):
    """send_image 完整流程：加密 → getuploadurl → 上传 → sendmessage。"""
    ch = _channel()
    ch.config = WeixinChannelConfig(
        enabled=True, account_id="bot", user_id="bot",
        token="test_token",
    )
    ch._context_tokens = {"wx_user": "ctx_tok"}

    # 准备图片文件
    img_path = tmp_path / "test.png"
    plaintext = b"PNG fake content"
    img_path.write_bytes(plaintext)
    ch._send_session = MagicMock()

    # mock 各步骤
    from illusion_forge.channels.weixin import ilink_api

    async def fake_get_upload_url(session, **kwargs):
        return {"upload_param": "upload_param_123", "upload_full_url": ""}

    async def fake_upload_ciphertext(session, *, ciphertext, upload_url):
        return "encrypted_query_param_456"

    async def fake_api_post(session, *, base_url, endpoint, payload, token, timeout_ms):
        return {"errcode": 0}

    monkeypatch_api_post = fake_api_post

    original_get_upload = ilink_api.get_upload_url
    original_upload_cipher = ilink_api.upload_ciphertext
    original_api_post = ilink_api._api_post

    ilink_api.get_upload_url = fake_get_upload_url
    ilink_api.upload_ciphertext = fake_upload_ciphertext
    ilink_api._api_post = monkeypatch_api_post

    try:
        msg_id = await ch.send_image("wx_user", str(img_path))
    finally:
        ilink_api.get_upload_url = original_get_upload
        ilink_api.upload_ciphertext = original_upload_cipher
        ilink_api._api_post = original_api_post

    assert msg_id.startswith("illusion-weixin-")


@pytest.mark.asyncio
async def test_send_document_uses_file_item(tmp_path):
    """send_document 走 ITEM_FILE 通道。"""
    ch = _channel()
    ch.config = WeixinChannelConfig(
        enabled=True, account_id="bot", user_id="bot",
        token="test_token",
    )
    ch._context_tokens = {}

    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"PDF content")
    ch._send_session = MagicMock()

    from illusion_forge.channels.weixin import ilink_api

    captured_payload = {}

    async def fake_get_upload_url(session, **kwargs):
        return {"upload_full_url": "https://novac2c.cdn.weixin.qq.com/c2c/upload?x=1"}

    async def fake_upload_ciphertext(session, *, ciphertext, upload_url):
        return "file_enc_param"

    async def fake_api_post(session, *, base_url, endpoint, payload, token, timeout_ms):
        captured_payload.update(payload)
        return {"errcode": 0}

    original_get_upload = ilink_api.get_upload_url
    original_upload_cipher = ilink_api.upload_ciphertext
    original_api_post = ilink_api._api_post

    ilink_api.get_upload_url = fake_get_upload_url
    ilink_api.upload_ciphertext = fake_upload_ciphertext
    ilink_api._api_post = fake_api_post

    try:
        await ch.send_document("wx_user", str(file_path), caption="请查收")
    finally:
        ilink_api.get_upload_url = original_get_upload
        ilink_api.upload_ciphertext = original_upload_cipher
        ilink_api._api_post = original_api_post

    # 验证 media item 类型为 ITEM_FILE
    from illusion_forge.channels.weixin.ilink_api import ITEM_FILE
    items = captured_payload["msg"]["item_list"]
    assert any(it["type"] == ITEM_FILE for it in items)
    file_item = next(it["file_item"] for it in items if it["type"] == ITEM_FILE)
    assert file_item["file_name"] == "doc.pdf"
    assert file_item["media"]["encrypt_query_param"] == "file_enc_param"


@pytest.mark.asyncio
async def test_send_file_routes_by_extension(tmp_path):
    """send_file 按扩展名路由：.jpg → send_image，.pdf → send_document。"""
    ch = _channel()
    ch.config = WeixinChannelConfig(
        enabled=True, account_id="bot", user_id="bot",
        token="test_token",
    )
    ch._context_tokens = {}

    # 创建两个文件
    img_path = tmp_path / "pic.jpg"
    img_path.write_bytes(b"img")
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"pdf")

    ch._send_session = MagicMock()

    from illusion_forge.channels.weixin import ilink_api

    call_log = []

    async def fake_get_upload_url(session, **kwargs):
        call_log.append(("get_upload_url", kwargs["media_type"]))
        return {"upload_full_url": "https://novac2c.cdn.weixin.qq.com/c2c/upload?x=1"}

    async def fake_upload_ciphertext(session, *, ciphertext, upload_url):
        return "enc_param"

    async def fake_api_post(session, *, base_url, endpoint, payload, token, timeout_ms):
        return {"errcode": 0}

    original_get_upload = ilink_api.get_upload_url
    original_upload_cipher = ilink_api.upload_ciphertext
    original_api_post = ilink_api._api_post

    ilink_api.get_upload_url = fake_get_upload_url
    ilink_api.upload_ciphertext = fake_upload_ciphertext
    ilink_api._api_post = fake_api_post

    try:
        await ch.send_file("wx_user", str(img_path))
        await ch.send_file("wx_user", str(pdf_path))
    finally:
        ilink_api.get_upload_url = original_get_upload
        ilink_api.upload_ciphertext = original_upload_cipher
        ilink_api._api_post = original_api_post

    from illusion_forge.channels.weixin.ilink_api import MEDIA_FILE, MEDIA_IMAGE
    media_types = [m for _, m in call_log]
    assert MEDIA_IMAGE in media_types  # jpg 走 image
    assert MEDIA_FILE in media_types  # pdf 走 file


@pytest.mark.asyncio
async def test_send_file_raises_without_session(tmp_path):
    """未连接时 send_image 抛 RuntimeError。"""
    ch = _channel()
    ch._send_session = None
    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"img")
    with pytest.raises(RuntimeError, match="未连接"):
        await ch.send_image("wx_user", str(img_path))


@pytest.mark.asyncio
async def test_send_file_raises_without_token(tmp_path):
    """token 未配置时 send_image 抛 RuntimeError。"""
    ch = _channel()
    ch.config = WeixinChannelConfig(
        enabled=True, account_id="bot", user_id="bot", token="",
    )
    ch._send_session = MagicMock()
    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"img")
    with pytest.raises(RuntimeError, match="token"):
        await ch.send_image("wx_user", str(img_path))


# ─── AES 密钥缓存管理测试 ─────────────────────────────────────


def test_get_aes_key_returns_cached_value():
    """_get_aes_key 从缓存返回有效密钥。"""
    ch = _channel()
    ch._aes_key_cache["msg_1:1"] = ("aes_b64_value", float("inf"))
    assert ch._get_aes_key("msg_1", "1") == "aes_b64_value"


def test_get_aes_key_returns_empty_for_missing():
    """_get_aes_key 缓存未命中返回空串。"""
    ch = _channel()
    assert ch._get_aes_key("msg_1", "1") == ""


def test_get_aes_key_returns_empty_for_expired():
    """_get_aes_key 过期缓存返回空串。"""
    ch = _channel()
    import time as _time
    ch._aes_key_cache["msg_1:1"] = ("aes_b64_value", _time.monotonic() - 1)
    assert ch._get_aes_key("msg_1", "1") == ""
    # 过期项应被清理
    assert "msg_1:1" not in ch._aes_key_cache


def test_cleanup_aes_cache_skips_below_threshold():
    """缓存项少于 100 时跳过清理。"""
    ch = _channel()
    import time as _time
    # 添加 50 个过期项
    for i in range(50):
        ch._aes_key_cache[f"msg_{i}:1"] = ("aes", _time.monotonic() - 100)
    ch._cleanup_aes_cache()
    # 仍未到阈值，不应清理
    assert len(ch._aes_key_cache) == 50


def test_cleanup_aes_cache_removes_expired_above_threshold():
    """缓存项达 100 时清理过期项。"""
    ch = _channel()
    import time as _time
    # 80 个过期 + 30 个有效 = 110 项
    for i in range(80):
        ch._aes_key_cache[f"old_{i}:1"] = ("aes", _time.monotonic() - 100)
    for i in range(30):
        ch._aes_key_cache[f"new_{i}:1"] = ("aes", _time.monotonic() + 100)
    ch._cleanup_aes_cache()
    # 过期项被清理，有效项保留
    assert all(k.startswith("new_") for k in ch._aes_key_cache)
    assert len(ch._aes_key_cache) == 30


# ─── _check_crypto_available 测试 ──────────────────────────────


def test_check_crypto_available_returns_bool():
    """_check_crypto_available 返回 bool（依赖环境）。"""
    from illusion_forge.channels.weixin.ilink_api import _check_crypto_available
    result = _check_crypto_available()
    assert isinstance(result, bool)
