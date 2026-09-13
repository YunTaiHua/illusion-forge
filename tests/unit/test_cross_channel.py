"""测试跨渠道工具：ListChannelSessionsTool / SendToChannelTool"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from illusion_forge.channels.base import SessionInfo
from illusion_forge.channels.config import ChannelsConfig, FeishuChannelConfig
from illusion_forge.channels.tools.cross_channel import (
    ListChannelSessionsInput,
    ListChannelSessionsTool,
    SendToChannelInput,
    SendToChannelTool,
)
from illusion_forge.tools.base import ToolExecutionContext


def _make_ctx() -> ToolExecutionContext:
    """构造测试用 ToolExecutionContext"""
    return ToolExecutionContext(cwd=Path("/tmp"))


@pytest.mark.asyncio
async def test_send_to_channel_success(tmp_path: Path) -> None:
    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    cfg = ChannelsConfig(
        feishu=FeishuChannelConfig(enabled=True, app_id="x", app_secret="y"),
    )
    tool = SendToChannelTool(cfg)
    args = SendToChannelInput(
        channel_name="feishu", chat_id="ou_user1", file_path=str(file_path),
    )
    with patch(
        "illusion_forge.channels.tools.cross_channel.deliver_file_to_channel",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_deliver:
        result = await tool.execute(args, _make_ctx())
    assert not result.is_error
    assert "Sent" in result.output or "feishu" in result.output.lower()
    mock_deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_to_channel_file_not_found() -> None:
    cfg = ChannelsConfig(
        feishu=FeishuChannelConfig(enabled=True, app_id="x", app_secret="y"),
    )
    tool = SendToChannelTool(cfg)
    args = SendToChannelInput(
        channel_name="feishu", chat_id="ou_x", file_path="/nope.txt",
    )
    result = await tool.execute(args, _make_ctx())
    assert result.is_error
    assert "not found" in result.output.lower() or "failed" in result.output.lower()


@pytest.mark.asyncio
async def test_send_to_channel_channel_not_enabled(tmp_path: Path) -> None:
    file_path = tmp_path / "x.txt"
    file_path.write_text("x", encoding="utf-8")
    cfg = ChannelsConfig()
    tool = SendToChannelTool(cfg)
    args = SendToChannelInput(
        channel_name="feishu", chat_id="ou_x", file_path=str(file_path),
    )
    with patch(
        "illusion_forge.channels.tools.cross_channel.deliver_file_to_channel",
        new_callable=AsyncMock,
        return_value=False,
    ) as mock_deliver:
        result = await tool.execute(args, _make_ctx())
    assert result.is_error
    mock_deliver.assert_not_called()


def test_send_to_channel_input_model() -> None:
    """测试输入模型字段"""
    args = SendToChannelInput(
        channel_name="qq", chat_id="openid_1", file_path="/tmp/x",
    )
    assert args.channel_name == "qq"
    assert args.caption == ""


# ---------------------------------------------------------------------------
# ListChannelSessionsTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_channel_sessions_success() -> None:
    """成功返回会话列表时，输出包含 chat_id 并提示 LLM 询问用户确认"""
    cfg = ChannelsConfig(
        feishu=FeishuChannelConfig(enabled=True, app_id="x", app_secret="y"),
    )
    tool = ListChannelSessionsTool(cfg)
    args = ListChannelSessionsInput(channel_name="feishu", limit=5)
    fake_sessions = [
        SessionInfo(
            chat_id="ou_user1",
            user_name="Alice",
            chat_type="dm",
            last_active="2026-06-28 10:30",
        ),
        SessionInfo(
            chat_id="oc_group1",
            user_name="",
            chat_type="group",
            last_active="2026-06-28 09:00",
        ),
    ]
    # list_active_sessions 在 execute 内部 lazy import，patch 源头模块
    with patch(
        "illusion_forge.prompts.channel_hints.list_active_sessions",
        return_value=fake_sessions,
    ) as mock_list:
        result = await tool.execute(args, _make_ctx())
    assert not result.is_error
    assert "ou_user1" in result.output
    assert "Alice" in result.output
    assert "oc_group1" in result.output
    # 末尾应提示 LLM 让用户确认，不要直接发送
    assert "ask" in result.output.lower() or "confirm" in result.output.lower()
    mock_list.assert_called_once_with("feishu", cfg, limit=5)


@pytest.mark.asyncio
async def test_list_channel_sessions_empty() -> None:
    """无活跃会话时返回非错误提示"""
    cfg = ChannelsConfig(
        feishu=FeishuChannelConfig(enabled=True, app_id="x", app_secret="y"),
    )
    tool = ListChannelSessionsTool(cfg)
    args = ListChannelSessionsInput(channel_name="feishu")
    with patch(
        "illusion_forge.prompts.channel_hints.list_active_sessions",
        return_value=[],
    ):
        result = await tool.execute(args, _make_ctx())
    assert not result.is_error
    assert "no active sessions" in result.output.lower()


@pytest.mark.asyncio
async def test_list_channel_sessions_channel_not_enabled() -> None:
    """渠道未启用时返回错误且不调用 list_active_sessions"""
    cfg = ChannelsConfig()  # 所有渠道默认 disabled
    tool = ListChannelSessionsTool(cfg)
    args = ListChannelSessionsInput(channel_name="feishu")
    with patch(
        "illusion_forge.prompts.channel_hints.list_active_sessions",
        return_value=[],
    ) as mock_list:
        result = await tool.execute(args, _make_ctx())
    assert result.is_error
    assert "not enabled" in result.output.lower()
    mock_list.assert_not_called()


@pytest.mark.asyncio
async def test_list_channel_sessions_list_raises() -> None:
    """list_active_sessions 抛异常时，工具捕获并返回错误"""
    cfg = ChannelsConfig(
        feishu=FeishuChannelConfig(enabled=True, app_id="x", app_secret="y"),
    )
    tool = ListChannelSessionsTool(cfg)
    args = ListChannelSessionsInput(channel_name="feishu")
    with patch(
        "illusion_forge.prompts.channel_hints.list_active_sessions",
        side_effect=RuntimeError("boom"),
    ):
        result = await tool.execute(args, _make_ctx())
    assert result.is_error
    assert "failed to list sessions" in result.output.lower()
    assert "boom" in result.output


def test_list_channel_sessions_input_model() -> None:
    """输入模型默认 limit=10"""
    args = ListChannelSessionsInput(channel_name="qq")
    assert args.channel_name == "qq"
    assert args.limit == 10
