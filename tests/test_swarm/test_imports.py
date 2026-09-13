"""Import regression tests for swarm startup."""

from __future__ import annotations

import importlib
import sys


def test_create_default_tool_registry_imports_cleanly():
    """Test that creating the tool registry doesn't fail with the new simplified swarm module."""
    for module_name in list(sys.modules):
        if module_name == "illusion_forge.tools" or module_name.startswith("illusion_forge.tools."):
            sys.modules.pop(module_name, None)
        if module_name == "illusion_forge.swarm" or module_name.startswith("illusion_forge.swarm."):
            sys.modules.pop(module_name, None)

    tools = importlib.import_module("illusion_forge.tools")
    registry = tools.create_default_tool_registry()

    assert registry.get("bash") is not None
    assert registry.get("agent") is not None
    assert registry.get("send_message") is not None
    # Team tools are now registered by default
    assert registry.get("team_create") is not None
    assert registry.get("team_delete") is not None


def test_swarm_module_exports():
    """Test that the swarm module exports the expected API."""
    from illusion_forge.swarm import (
        AgentAbortController,
        AgentExecutionContext,
        AgentResult,
        AgentSpawnConfig,
        TaskNotification,
        TeammateMessage,
    )

    # Verify types exist
    assert AgentAbortController is not None
    assert AgentExecutionContext is not None
    assert AgentResult is not None
    assert AgentSpawnConfig is not None
    assert TaskNotification is not None
    assert TeammateMessage is not None


def test_task_notification_roundtrip():
    """Test that TaskNotification can be serialized and deserialized."""
    from illusion_forge.swarm import TaskNotification, format_task_notification, parse_task_notification

    original = TaskNotification(
        task_id="agent-123",
        status="completed",
        summary="Agent 'researcher' completed",
        result="Found 3 files matching the pattern.",
        usage={
            "total_tokens": 1500,
            "tool_uses": 5,
            "duration_ms": 3000,
        },
    )

    xml = format_task_notification(original)
    parsed = parse_task_notification(xml)

    assert parsed.task_id == original.task_id
    assert parsed.status == original.status
    assert parsed.summary == original.summary
    assert parsed.result == original.result
    assert parsed.usage == original.usage
