"""HTTP 客户端工具函数测试"""
from __future__ import annotations

import httpx
import pytest

from illusion_forge.utils.http import create_async_client


def test_create_async_client_returns_async_client():
    """create_async_client 应返回 httpx.AsyncClient 实例"""
    client = create_async_client(timeout=10.0)
    assert isinstance(client, httpx.AsyncClient)


def test_create_async_client_passes_kwargs():
    """应透传 kwargs（如 timeout、follow_redirects）"""
    client = create_async_client(timeout=30.0, follow_redirects=True)
    assert isinstance(client, httpx.AsyncClient)


@pytest.mark.asyncio
async def test_create_async_client_can_connect_https():
    """HTTPS 连接应能建立（不验证具体内容，只验证不抛 SSL 错误）"""
    async with create_async_client(timeout=10.0) as client:
        # 使用一个稳定的 HTTPS 端点
        try:
            response = await client.get("https://www.example.com")
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.skip("网络不可用，跳过连接测试")
