"""Tests for TaskNotification XML serialization."""

from __future__ import annotations

from illusion_forge.coordinator.coordinator_mode import (
    TaskNotification,
    format_task_notification,
    parse_task_notification,
)

# ---------------------------------------------------------------------------
# TaskNotification XML round-trip
# ---------------------------------------------------------------------------


def test_format_and_parse_basic():
    n = TaskNotification(task_id="t123", status="completed", summary="all done")
    xml = format_task_notification(n)
    assert "<task-notification>" in xml
    assert "<task-id>t123</task-id>" in xml
    assert "<status>completed</status>" in xml
    assert "<summary>all done</summary>" in xml

    parsed = parse_task_notification(xml)
    assert parsed.task_id == "t123"
    assert parsed.status == "completed"
    assert parsed.summary == "all done"
    assert parsed.result is None
    assert parsed.usage is None


def test_format_and_parse_with_result_and_usage():
    n = TaskNotification(
        task_id="abc",
        status="failed",
        summary="error occurred",
        result="traceback here",
        usage={"total_tokens": 42, "tool_uses": 3, "duration_ms": 1500},
    )
    xml = format_task_notification(n)
    assert "<result>traceback here</result>" in xml
    assert "<total_tokens>42</total_tokens>" in xml
    assert "<tool_uses>3</tool_uses>" in xml
    assert "<duration_ms>1500</duration_ms>" in xml

    parsed = parse_task_notification(xml)
    assert parsed.task_id == "abc"
    assert parsed.status == "failed"
    assert parsed.result == "traceback here"
    assert parsed.usage == {"total_tokens": 42, "tool_uses": 3, "duration_ms": 1500}


def test_parse_ignores_missing_optional_fields():
    xml = "<task-notification><task-id>x</task-id><status>completed</status><summary>ok</summary></task-notification>"
    parsed = parse_task_notification(xml)
    assert parsed.task_id == "x"
    assert parsed.result is None
    assert parsed.usage is None


def test_parse_partial_usage_block():
    xml = (
        "<task-notification>"
        "<task-id>y</task-id><status>completed</status><summary>ok</summary>"
        "<usage><total_tokens>100</total_tokens></usage>"
        "</task-notification>"
    )
    parsed = parse_task_notification(xml)
    assert parsed.usage == {"total_tokens": 100}
