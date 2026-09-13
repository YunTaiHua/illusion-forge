"""ilink_api 上传重试测试

验证 _retry_transient 对瞬时错误自动重试，对 4xx 业务错误不重试。
"""
from __future__ import annotations

import pytest
from aiohttp import ClientError as aiohttp_ClientError


@pytest.mark.asyncio
async def test_retry_transient_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """瞬时错误（连接错误）应重试直至成功"""
    from illusion_forge.channels.weixin import ilink_api

    # 压缩退避，加速测试
    monkeypatch.setattr(ilink_api, "UPLOAD_BACKOFF_SECONDS", (0.01, 0.01, 0.01))

    call_count = {"n": 0}

    async def flaky() -> dict:
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise aiohttp_ClientError("transient network error")
        return {"ok": True}

    result = await ilink_api._retry_transient(flaky, name="test", max_attempts=5)
    assert result == {"ok": True}
    assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_no_retry_on_business_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """业务错误（RuntimeError 含 HTTP 4xx）不应重试"""
    from illusion_forge.channels.weixin import ilink_api

    monkeypatch.setattr(ilink_api, "UPLOAD_BACKOFF_SECONDS", (0.01, 0.01, 0.01))

    call_count = {"n": 0}

    async def business_err() -> dict:
        call_count["n"] += 1
        raise RuntimeError("iLink POST HTTP 400: bad request")

    with pytest.raises(RuntimeError):
        await ilink_api._retry_transient(business_err, name="test", max_attempts=5)
    assert call_count["n"] == 1, "4xx 业务错误不应重试"


@pytest.mark.asyncio
async def test_retry_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """持续瞬时错误超过最大尝试次数后抛出最后异常"""
    from illusion_forge.channels.weixin import ilink_api

    monkeypatch.setattr(ilink_api, "UPLOAD_BACKOFF_SECONDS", (0.01, 0.01, 0.01))

    call_count = {"n": 0}

    async def always_fail() -> dict:
        call_count["n"] += 1
        raise aiohttp_ClientError("always fails")

    with pytest.raises(aiohttp_ClientError):
        await ilink_api._retry_transient(always_fail, name="test", max_attempts=3)
    assert call_count["n"] == 3
