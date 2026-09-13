"""--verbose/--debug/--bare 参数测试。"""
from __future__ import annotations

import logging

import pytest

from illusion_forge.api.client import ApiMessageCompleteEvent
from illusion_forge.api.usage import UsageSnapshot
from illusion_forge.engine.messages import ConversationMessage, TextBlock


class StaticApiClient:
    """Fake streaming client for verbose/debug/bare tests."""

    async def stream_message(self, request):
        del request
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=[TextBlock(text="ok")]),
            usage=UsageSnapshot(input_tokens=2, output_tokens=3),
            stop_reason=None,
        )


@pytest.mark.asyncio
async def test_bare_mode_skips_plugins(tmp_path, monkeypatch):
    """--bare 模式应跳过插件加载。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    loaded = False

    def mock_load_plugins(*args, **kwargs):
        nonlocal loaded
        loaded = True
        return []

    from illusion_forge.ui import runtime as rt
    monkeypatch.setattr(rt, "load_plugins", mock_load_plugins)

    bundle = await rt.build_runtime(
        api_client=StaticApiClient(),
        bare=True,
    )
    try:
        assert loaded is False
        # --bare 模式 mcp_manager 应存在但无服务器
        assert bundle.mcp_manager is not None
        assert bundle.mcp_manager.list_statuses() == []
    finally:
        await rt.close_runtime(bundle)


@pytest.mark.asyncio
async def test_verbose_sets_info_level(tmp_path, monkeypatch):
    """--verbose 应设置 INFO 日志级别。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.runtime import build_runtime, close_runtime

    bundle = await build_runtime(api_client=StaticApiClient(), verbose=True)
    try:
        assert logging.getLogger("illusion_forge").level == logging.INFO
    finally:
        await close_runtime(bundle)


@pytest.mark.asyncio
async def test_debug_sets_debug_level(tmp_path, monkeypatch):
    """--debug 应设置 DEBUG 日志级别。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.runtime import build_runtime, close_runtime

    bundle = await build_runtime(api_client=StaticApiClient(), debug=True)
    try:
        assert logging.getLogger("illusion_forge").level == logging.DEBUG
    finally:
        await close_runtime(bundle)
