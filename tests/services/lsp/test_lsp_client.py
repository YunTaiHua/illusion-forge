"""LSP 客户端测试。"""

from __future__ import annotations

import pytest

from illusion_forge.services.lsp.client import LspClient


class TestLspClient:
    """LspClient 生命周期测试。"""

    @pytest.mark.asyncio
    async def test_client_starts_uninitialized(self):
        client = LspClient()
        assert not client.is_initialized
        assert client.capabilities is None

    @pytest.mark.asyncio
    async def test_request_without_start_raises(self):
        client = LspClient()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.request("textDocument/definition", {"textDocument": {}, "position": {}})
