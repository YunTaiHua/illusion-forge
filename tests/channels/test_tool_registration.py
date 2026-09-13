"""渠道工具注册透传测试。"""
from __future__ import annotations

from pydantic import BaseModel

from illusion_forge.tools import create_default_tool_registry
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult


class _FakeInput(BaseModel):
    """测试用输入。"""


class _FakeTool(BaseTool):
    """测试用工具。"""
    name = "test_channel_tool"
    description = "Test tool"
    input_model = _FakeInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output="ok")


def test_channel_tools_registered():
    """channel_tools 参数的工具被注册到 registry。"""
    registry = create_default_tool_registry(channel_tools=[_FakeTool()])
    assert registry.get("test_channel_tool") is not None


def test_no_channel_tools_works():
    """不传 channel_tools 时正常工作（向后兼容）。"""
    registry = create_default_tool_registry()
    assert registry.get("test_channel_tool") is None  # 该工具未注册
    # 默认工具仍在（随便查一个内置工具名）
    tool_names = [t.name for t in registry.list_tools()]
    assert len(tool_names) > 0
