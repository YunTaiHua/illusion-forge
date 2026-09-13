"""--allowed-tools/--disallowed-tools/--mcp-config/--name 参数测试。"""
from __future__ import annotations

import pytest

from illusion_forge.api.client import ApiMessageCompleteEvent
from illusion_forge.api.usage import UsageSnapshot
from illusion_forge.engine.messages import ConversationMessage, TextBlock


class StaticApiClient:
    """Fake streaming client for CLI tool filter tests."""

    async def stream_message(self, request):
        del request
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=[TextBlock(text="ok")]),
            usage=UsageSnapshot(input_tokens=2, output_tokens=3),
            stop_reason=None,
        )


@pytest.mark.asyncio
async def test_allowed_tools_filters_registry(tmp_path, monkeypatch):
    """--allowed-tools 应过滤工具注册表，只保留白名单中的工具。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.runtime import build_runtime, close_runtime

    bundle = await build_runtime(
        api_client=StaticApiClient(),
        bare=True,
        allowed_tools=["bash", "read_file"],
    )
    try:
        tool_names = {t.name for t in bundle.tool_registry.list_tools()}
        assert tool_names == {"bash", "read_file"}, f"Expected only bash+read_file, got {tool_names}"
    finally:
        await close_runtime(bundle)


@pytest.mark.asyncio
async def test_disallowed_tools_removes_from_registry(tmp_path, monkeypatch):
    """--disallowed-tools 应从注册表中移除黑名单工具。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.runtime import build_runtime, close_runtime

    bundle = await build_runtime(
        api_client=StaticApiClient(),
        bare=True,
        disallowed_tools=["bash", "powershell"],
    )
    try:
        tool_names = {t.name for t in bundle.tool_registry.list_tools()}
        assert "bash" not in tool_names
        assert "powershell" not in tool_names
        # 其他工具应该还在
        assert "read_file" in tool_names
    finally:
        await close_runtime(bundle)


@pytest.mark.asyncio
async def test_name_stored_in_tool_metadata(tmp_path, monkeypatch):
    """--name 应存储到 tool_metadata 中。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.runtime import build_runtime, close_runtime

    bundle = await build_runtime(
        api_client=StaticApiClient(),
        bare=True,
        name="my-test-session",
    )
    try:
        assert bundle.engine._tool_metadata.get("session_name") == "my-test-session"
    finally:
        await close_runtime(bundle)


@pytest.mark.asyncio
async def test_mcp_config_loads_from_json_string(tmp_path, monkeypatch):
    """--mcp-config 应从 JSON 字符串加载 MCP 服务器配置。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.runtime import build_runtime, close_runtime

    # 使用一个无效的 command，服务器会连接失败但配置应被加载
    mcp_json = '{"mcpServers": {"test-server": {"type": "stdio", "command": "echo", "args": ["hi"]}}}'
    bundle = await build_runtime(
        api_client=StaticApiClient(),
        bare=True,
        mcp_config=[mcp_json],
    )
    try:
        statuses = bundle.mcp_manager.list_statuses()
        status_names = {s.name for s in statuses}
        assert "test-server" in status_names, f"Expected test-server in {status_names}"
    finally:
        await close_runtime(bundle)


@pytest.mark.asyncio
async def test_mcp_config_invalid_json_logs_warning(tmp_path, monkeypatch):
    """--mcp-config 无效 JSON 应记录警告但不崩溃。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.runtime import build_runtime, close_runtime

    bundle = await build_runtime(
        api_client=StaticApiClient(),
        bare=True,
        mcp_config=["not-valid-json{{{"],
    )
    try:
        # 无效 JSON 不应崩溃，mcp_manager 应为空
        statuses = bundle.mcp_manager.list_statuses()
        assert len(statuses) == 0
    finally:
        await close_runtime(bundle)
