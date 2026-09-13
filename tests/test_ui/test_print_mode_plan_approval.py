"""Tests for print mode plan approval cross-turn mechanism."""

from __future__ import annotations

from illusion_forge.ui.headless import _inject_plan_approval_to_tool_result, _parse_plan_approval
from illusion_forge.ui.headless_prompts import PENDING_PLAN_APPROVAL_MARKER


def test_parse_plan_approval_approve():
    """测试批准关键词解析"""
    for keyword in ("批准", "approve", "yes", "y", "APPROVE", "Yes"):
        result = _parse_plan_approval(keyword)
        assert result["approved"] is True
        assert result["feedback"] == ""


def test_parse_plan_approval_reject_with_feedback():
    """测试非批准输入视为拒绝+反馈"""
    result = _parse_plan_approval("需要增加测试用例")
    assert result["approved"] is False
    assert result["feedback"] == "需要增加测试用例"


def test_parse_plan_approval_empty_input():
    """测试空输入视为拒绝"""
    result = _parse_plan_approval("")
    assert result["approved"] is False
    assert "rejected" in result["feedback"].lower()


def test_inject_plan_approval_approved():
    """测试批准结果注入"""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "abc", "content": PENDING_PLAN_APPROVAL_MARKER}
            ],
        }
    ]
    result = _inject_plan_approval_to_tool_result(messages, {"approved": True, "feedback": ""})
    assert result[0]["content"][0]["content"] == "Plan approved. Starting implementation."
    assert result[0]["content"][0]["is_error"] is False


def test_inject_plan_approval_rejected():
    """测试拒绝结果注入"""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "abc", "content": PENDING_PLAN_APPROVAL_MARKER}
            ],
        }
    ]
    result = _inject_plan_approval_to_tool_result(
        messages, {"approved": False, "feedback": "需要修改"}
    )
    assert "需要修改" in result[0]["content"][0]["content"]
    assert result[0]["content"][0]["is_error"] is True
