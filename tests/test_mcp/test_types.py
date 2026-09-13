"""MCP_TOOL_EXCEPTIONS 常量测试。

验证 MCP 工具异常捕获列表包含正确的异常类型，
确保 ValueError 和 MCPError 都能被 except 子句捕获。
"""

from __future__ import annotations

from mcp.shared.exceptions import MCPError

from illusion_forge.mcp.types import MCP_TOOL_EXCEPTIONS


def test_contains_value_error() -> None:
    """MCP_TOOL_EXCEPTIONS 应包含 ValueError。"""
    assert ValueError in MCP_TOOL_EXCEPTIONS


def test_contains_mcp_error() -> None:
    """MCP_TOOL_EXCEPTIONS 应包含 MCPError。"""
    assert MCPError in MCP_TOOL_EXCEPTIONS


def test_catches_value_error() -> None:
    """except MCP_TOOL_EXCEPTIONS 应能捕获 ValueError。"""
    try:
        raise ValueError("test error")
    except MCP_TOOL_EXCEPTIONS as exc:
        assert str(exc) == "test error"
    else:
        raise AssertionError("ValueError should be caught by MCP_TOOL_EXCEPTIONS")


def test_catches_mcp_error() -> None:
    """except MCP_TOOL_EXCEPTIONS 应能捕获 MCPError。"""
    try:
        raise MCPError(code=-1, message="test mcp error")
    except MCP_TOOL_EXCEPTIONS as exc:
        assert "test mcp error" in str(exc)
    else:
        raise AssertionError("MCPError should be caught by MCP_TOOL_EXCEPTIONS")


def test_does_not_catch_runtime_error() -> None:
    """MCP_TOOL_EXCEPTIONS 不应捕获 RuntimeError（非预期异常）。"""
    caught = False
    try:
        raise RuntimeError("unexpected")
    except MCP_TOOL_EXCEPTIONS:
        caught = True
    except RuntimeError:
        pass
    assert not caught, "RuntimeError should not be caught by MCP_TOOL_EXCEPTIONS"
