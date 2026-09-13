"""Tests for web fetch and search tools."""

from __future__ import annotations

import contextlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from illusion_forge.tools.base import ToolExecutionContext
from illusion_forge.tools.web_fetch_tool import WebFetchTool, WebFetchToolInput
from illusion_forge.tools.web_search_tool import WebSearchTool, WebSearchToolInput


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query).get("q", [""])[0]
        if query:
            body = (
                "<html><body>"
                '<a class="result__a" href="https://example.com/docs">IllusionAgent Docs</a>'
                f'<div class="result__snippet">Search query was {query} and docs were found.</div>'
                "</body></html>"
            )
        else:
            body = "<html><body><h1>IllusionAgent Test</h1><p>web fetch works</p></body></html>"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:
        del format, args


def _make_mock_response(html: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.text = html
    mock_resp.is_redirect = False
    mock_resp.raise_for_status = MagicMock()
    mock_resp.url = "https://example.com/"
    return mock_resp


@pytest.mark.asyncio
async def test_web_fetch_tool_reads_html(tmp_path, monkeypatch):
    mock_resp = _make_mock_response(
        "<html><body><h1>IllusionAgent Test</h1><p>web fetch works</p></body></html>"
    )
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    async def _fake_process_with_model(content: str, prompt: str) -> str:
        return f"Summary: {content[:50]}"

    def _fake_cache_get(*args, **kwargs) -> None:
        return None

    # 全套件运行时，某些测试可能导致 web_fetch_tool 模块被重新加载，
    # 使 WebFetchTool.execute.__globals__ 与 sys.modules 中的模块 __dict__
    # 不再是同一对象。直接在 execute.__globals__ 上注入 mock 可确保 patch 生效。
    execute_globals = WebFetchTool.execute.__globals__
    monkeypatch.setitem(execute_globals, "_process_with_model", _fake_process_with_model)
    monkeypatch.setitem(execute_globals, "_cache_get", _fake_cache_get)

    with patch("illusion_forge.tools.web_fetch_tool.httpx.AsyncClient", return_value=mock_client):
        tool = WebFetchTool()
        result = await tool.execute(
            WebFetchToolInput(url="https://example.com/"),
            ToolExecutionContext(cwd=tmp_path),
        )

    assert result.is_error is False
    assert "Summary:" in result.output


@pytest.mark.asyncio
async def test_web_search_tool_reads_results(tmp_path):
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        tool = WebSearchTool()
        result = await tool.execute(
            WebSearchToolInput(
                query="illusion docs",
                search_url=f"http://127.0.0.1:{server.server_port}/search",
            ),
            ToolExecutionContext(cwd=tmp_path),
        )
    finally:
        server.shutdown()
        with contextlib.suppress(Exception):
            server.server_close()
        thread.join(timeout=1)

    assert result.is_error is False
    assert "IllusionAgent Docs" in result.output
    assert "https://example.com/docs" in result.output
    assert "illusion docs" in result.output
