""" /agent 命令处理器测试 """
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from illusion_forge.commands.agent import agent_handler
from illusion_forge.commands.types import CommandContext
from illusion_forge.engine.messages import ConversationMessage, TextBlock, ToolResultBlock, ToolUseBlock


def _ctx(engine_messages=None):
    engine = MagicMock()
    engine.messages = engine_messages or []
    return CommandContext(engine=engine, cwd="."), engine


def _notification_text(task_id: str, status: str = "completed", summary: str = "Agent 'explore' completed", result: str = "这是 agent 的最终摘要回复") -> str:
    """构造一个 task-notification TextBlock 文本。"""
    return (
        f"<task-notification>\n<task-id>{task_id}</task-id>\n"
        f"<status>{status}</status>\n"
        f"<summary>{summary}</summary>\n"
        f"<result>{result}</result>\n"
        f"<usage>\n  <total_tokens>100</total_tokens>\n  <tool_uses>0</tool_uses>\n  <duration_ms>39993</duration_ms>\n</usage>\n"
        f"</task-notification>"
    )


@pytest.mark.asyncio
async def test_agent_no_args_returns_list_hint():
    ctx, _ = _ctx()
    result = await agent_handler("", ctx)
    assert result.message is not None


@pytest.mark.asyncio
async def test_agent_create_returns_hint():
    ctx, _ = _ctx()
    result = await agent_handler("create", ctx)
    assert "creation" in (result.message or "").lower() or "wizard" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_agent_foreground_returns_tool_result():
    """前台 agent：<id> 为 tool_use_id，从 transcript 返回 tool_result 内容。"""
    tool_use_id = "toolu_abc123"
    messages = [
        ConversationMessage(role="assistant", content=[
            ToolUseBlock(id=tool_use_id, name="agent", input={"name": "test-runner"}),
        ]),
        ConversationMessage(role="user", content=[
            ToolResultBlock(tool_use_id=tool_use_id, content="前台 agent 的最终回复"),
        ]),
    ]
    ctx, _ = _ctx(messages)
    result = await agent_handler(tool_use_id, ctx)
    assert result.message == "前台 agent 的最终回复"


@pytest.mark.asyncio
async def test_agent_foreground_empty_tool_result():
    """前台 agent：tool_result 内容为空，返回 'Agent tool result ... is empty.' 提示。"""
    tool_use_id = "toolu_empty"
    messages = [
        ConversationMessage(role="user", content=[
            ToolResultBlock(tool_use_id=tool_use_id, content=""),
        ]),
    ]
    ctx, _ = _ctx(messages)
    result = await agent_handler(tool_use_id, ctx)
    assert result.message == f"Agent tool result '{tool_use_id}' is empty."


@pytest.mark.asyncio
async def test_agent_foreground_skips_launched_notification():
    """前台 agent：tool_result 内容为 'launched in background' 启动通知，跳过不返回，
    继续查找 task-notification；找不到则返回 'No task found'。
    保持与 select_command('agent') 一致的前台过滤逻辑。"""
    tool_use_id = "toolu_launched"
    messages = [
        ConversationMessage(role="user", content=[
            ToolResultBlock(tool_use_id=tool_use_id, content="Agent launched in background"),
        ]),
    ]
    ctx, _ = _ctx(messages)
    result = await agent_handler(tool_use_id, ctx)
    # 不应返回启动通知文本
    assert result.message != "Agent launched in background"
    # 应落入 "找不到" 分支
    assert "No task found with id" in (result.message or "")


@pytest.mark.asyncio
async def test_agent_foreground_launched_as_subprocess_also_skipped():
    """前台 agent：'launched as subprocess' 变体同样跳过。"""
    tool_use_id = "toolu_subproc"
    messages = [
        ConversationMessage(role="user", content=[
            ToolResultBlock(tool_use_id=tool_use_id, content="Agent launched as subprocess"),
        ]),
    ]
    ctx, _ = _ctx(messages)
    result = await agent_handler(tool_use_id, ctx)
    assert result.message != "Agent launched as subprocess"
    assert "No task found with id" in (result.message or "")


@pytest.mark.asyncio
async def test_agent_background_returns_notification_result():
    """后台 agent：从 transcript 的 task-notification 提取 <result> 内容。"""
    task_id = "a0a00c637"
    messages = [
        ConversationMessage(role="user", content=[
            TextBlock(text=_notification_text(task_id=task_id, result="这是 agent 的最终摘要回复")),
        ]),
    ]
    ctx, _ = _ctx(messages)
    result = await agent_handler(task_id, ctx)
    assert result.message == "这是 agent 的最终摘要回复"


@pytest.mark.asyncio
async def test_agent_background_multiline_result_preserved():
    """后台 agent：<result> 多行内容完整保留（正则使用 re.DOTALL）。"""
    task_id = "a0a00c638"
    multiline_result = "文件 `E:\\PyCode\\illusion-agent\\pyproject.toml` 的完整内容如下：\n\n```toml\n[project]\nname = \"illusion\"\n```"
    messages = [
        ConversationMessage(role="user", content=[
            TextBlock(text=_notification_text(task_id=task_id, result=multiline_result)),
        ]),
    ]
    ctx, _ = _ctx(messages)
    result = await agent_handler(task_id, ctx)
    assert result.message == multiline_result


@pytest.mark.asyncio
async def test_agent_background_not_completed():
    """后台 agent：task-notification status='running'，返回未完成消息。"""
    task_id = "a0a00c639"
    messages = [
        ConversationMessage(role="user", content=[
            TextBlock(text=_notification_text(task_id=task_id, status="running")),
        ]),
    ]
    ctx, _ = _ctx(messages)
    result = await agent_handler(task_id, ctx)
    assert result.message == f"Agent '{task_id}' is not completed (status: running)."


@pytest.mark.asyncio
async def test_agent_background_empty_result_returns_hint():
    """后台 agent：<result> 为空，返回 'Agent ... has no captured output.' 提示。"""
    task_id = "a0a00c640"
    messages = [
        ConversationMessage(role="user", content=[
            TextBlock(text=_notification_text(task_id=task_id, result="")),
        ]),
    ]
    ctx, _ = _ctx(messages)
    result = await agent_handler(task_id, ctx)
    assert result.message == f"Agent '{task_id}' has no captured output."


@pytest.mark.asyncio
async def test_agent_background_ignores_non_notification_text():
    """后台 agent：TextBlock 文本不含 task-notification，不应误匹配。"""
    messages = [
        ConversationMessage(role="user", content=[
            TextBlock(text="这只是普通用户消息，不是 task-notification"),
        ]),
    ]
    ctx, _ = _ctx(messages)
    result = await agent_handler("any_id", ctx)
    assert "No task found with id" in (result.message or "")


@pytest.mark.asyncio
async def test_agent_foreground_precedes_background():
    """前台 tool_result 优先于后台 task-notification：同 id 时返回前台结果。"""
    shared_id = "toolu_shared"
    fg_text = "前台 agent 摘要"
    messages = [
        ConversationMessage(role="user", content=[
            ToolResultBlock(tool_use_id=shared_id, content=fg_text),
        ]),
        ConversationMessage(role="user", content=[
            TextBlock(text=_notification_text(task_id=shared_id, result="后台 agent 摘要")),
        ]),
    ]
    ctx, _ = _ctx(messages)
    result = await agent_handler(shared_id, ctx)
    assert result.message == fg_text


@pytest.mark.asyncio
async def test_agent_unknown_id_returns_not_found():
    """既不在前台 transcript，也不在 task-notification，返回 'No task found'。"""
    ctx, _ = _ctx([])
    result = await agent_handler("nonexistent", ctx)
    assert "No task found with id" in (result.message or "")
