"""run_query 进度回调机制回归测试。

验证 ToolExecutionContext.on_progress 回调上报的消息被 run_query 主循环
转换为 ToolProgressEvent 流式事件。该机制仅用于 agent 工具前台模式，
其他工具不调用 on_progress，因此不产生 ToolProgressEvent。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from illusion_forge.api.client import ApiMessageCompleteEvent
from illusion_forge.api.usage import UsageSnapshot
from illusion_forge.config.settings import PermissionSettings
from illusion_forge.engine.messages import ConversationMessage, TextBlock, ToolUseBlock
from illusion_forge.engine.query import QueryContext, run_query
from illusion_forge.engine.stream_events import (
    ToolExecutionCompleted,
    ToolProgressEvent,
)
from illusion_forge.permissions import PermissionChecker
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult


class _EmptyInput(BaseModel):
    """进度工具的空输入模型。"""


class _ProgressTool(BaseTool[_EmptyInput]):
    """测试工具：执行期间通过 on_progress 上报多条进度消息。"""

    name = "progress_tool"
    description = "Test tool that emits progress messages."
    input_model = _EmptyInput

    async def execute(self, arguments: _EmptyInput, context: ToolExecutionContext) -> ToolResult:
        del arguments
        if context.on_progress is not None:
            await context.on_progress("Step 1: starting")
            await asyncio.sleep(0)  # 让出控制权，让 run_query drain 队列
            await context.on_progress("Step 2: working")
            await asyncio.sleep(0)
            await context.on_progress("Step 3: finishing")
        return ToolResult(output="done")

    def is_read_only(self, arguments: _EmptyInput) -> bool:
        """标记为只读，避免在 DEFAULT 权限模式下触发确认。"""
        del arguments
        return True


class _FakeApiClient:
    """返回预设助手消息的伪 API 客户端。"""

    def __init__(self, messages: list[ConversationMessage]) -> None:
        self._messages = list(messages)
        self._call_count = 0

    async def stream_message(self, request):
        del request
        message = self._messages[self._call_count]
        self._call_count += 1
        yield ApiMessageCompleteEvent(
            message=message,
            usage=UsageSnapshot(input_tokens=1, output_tokens=1),
            stop_reason=None,
        )


def _build_context(tmp_path: Path, registry: ToolRegistry) -> QueryContext:
    return QueryContext(
        api_client=_FakeApiClient([]),  # 占位，测试中替换
        tool_registry=registry,
        permission_checker=PermissionChecker(PermissionSettings()),
        cwd=tmp_path,
        model="test-model",
        system_prompt="system",
        max_tokens=128,
    )


@pytest.mark.asyncio
async def test_run_query_yields_tool_progress_events(tmp_path: Path):
    """单工具路径：工具执行期间 on_progress 上报的消息应被转换为 ToolProgressEvent。"""
    registry = ToolRegistry()
    registry.register(_ProgressTool())

    api_client = _FakeApiClient(
        [
            ConversationMessage(
                role="assistant",
                content=[
                    TextBlock(text="Calling progress tool."),
                    ToolUseBlock(id="toolu_progress_1", name="progress_tool", input={}),
                ],
            ),
            ConversationMessage(
                role="assistant",
                content=[TextBlock(text="Done.")],
            ),
        ]
    )

    context = _build_context(tmp_path, registry)
    context.api_client = api_client  # type: ignore[assignment]
    messages = [ConversationMessage.from_user_text("run the progress tool")]

    events: list = []
    async for event, _usage in run_query(context, messages):
        events.append(event)

    progress_events = [e for e in events if isinstance(e, ToolProgressEvent)]
    assert len(progress_events) == 3, f"期望 3 个 ToolProgressEvent，实际 {len(progress_events)}"
    assert progress_events[0].message == "Step 1: starting"
    assert progress_events[1].message == "Step 2: working"
    assert progress_events[2].message == "Step 3: finishing"
    # 所有进度事件的 tool_use_id 应与工具调用 ID 一致
    for pe in progress_events:
        assert pe.tool_use_id == "toolu_progress_1"

    # 验证进度事件位于 ToolExecutionCompleted 之前
    completed_idx = next(i for i, e in enumerate(events) if isinstance(e, ToolExecutionCompleted))
    last_progress_idx = max(i for i, e in enumerate(events) if isinstance(e, ToolProgressEvent))
    assert last_progress_idx < completed_idx, "进度事件应在 ToolExecutionCompleted 之前"


@pytest.mark.asyncio
async def test_run_query_progress_events_preserve_order(tmp_path: Path):
    """多个进度消息应保持上报顺序。"""
    registry = ToolRegistry()
    registry.register(_ProgressTool())

    api_client = _FakeApiClient(
        [
            ConversationMessage(
                role="assistant",
                content=[
                    ToolUseBlock(id="toolu_order", name="progress_tool", input={}),
                ],
            ),
            ConversationMessage(
                role="assistant",
                content=[TextBlock(text="finished")],
            ),
        ]
    )

    context = _build_context(tmp_path, registry)
    context.api_client = api_client  # type: ignore[assignment]
    messages = [ConversationMessage.from_user_text("go")]

    events: list = []
    async for event, _usage in run_query(context, messages):
        events.append(event)

    progress_events = [e for e in events if isinstance(e, ToolProgressEvent)]
    messages_text = [pe.message for pe in progress_events]
    assert messages_text == ["Step 1: starting", "Step 2: working", "Step 3: finishing"]


@pytest.mark.asyncio
async def test_run_query_no_progress_events_for_plain_tool(tmp_path: Path):
    """不调用 on_progress 的工具不应产生 ToolProgressEvent。"""
    sample = tmp_path / "data.txt"
    sample.write_text("content", encoding="utf-8")

    # 使用内置 read_file 工具（不调用 on_progress）
    from illusion_forge.tools import create_default_tool_registry

    registry = create_default_tool_registry()

    api_client = _FakeApiClient(
        [
            ConversationMessage(
                role="assistant",
                content=[
                    ToolUseBlock(
                        id="toolu_read",
                        name="read_file",
                        input={"path": str(sample), "offset": 0, "limit": 1},
                    ),
                ],
            ),
            ConversationMessage(
                role="assistant",
                content=[TextBlock(text="read done")],
            ),
        ]
    )

    context = _build_context(tmp_path, registry)
    context.api_client = api_client  # type: ignore[assignment]
    messages = [ConversationMessage.from_user_text("read")]

    events: list = []
    async for event, _usage in run_query(context, messages):
        events.append(event)

    progress_events = [e for e in events if isinstance(e, ToolProgressEvent)]
    assert len(progress_events) == 0, f"read_file 不应产生进度事件，实际 {len(progress_events)}"
    # 验证工具正常完成
    assert any(isinstance(e, ToolExecutionCompleted) for e in events)
