"""
钩子类型定义
============

定义钩子执行的输入和输出类型
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BaseHookInput:
    """钩子输入基础字段。"""

    session_id: str
    transcript_path: str
    cwd: str
    permission_mode: str | None = None
    agent_id: str | None = None
    agent_type: str | None = None


def create_base_hook_input(
    session_id: str = "",
    transcript_path: str = "",
    cwd: str = "",
    permission_mode: str | None = None,
    agent_id: str | None = None,
    agent_type: str | None = None,
) -> BaseHookInput:
    """创建 BaseHookInput 的工厂函数。"""
    return BaseHookInput(
        session_id=session_id,
        transcript_path=transcript_path,
        cwd=cwd,
        permission_mode=permission_mode,
        agent_id=agent_id,
        agent_type=agent_type,
    )


def create_hook_input(
    base: BaseHookInput,
    **extra: Any,
) -> dict[str, Any]:
    """创建完整的钩子输入字典。"""
    result: dict[str, Any] = {
        "session_id": base.session_id,
        "transcript_path": base.transcript_path,
        "cwd": base.cwd,
    }
    if base.permission_mode is not None:
        result["permission_mode"] = base.permission_mode
    if base.agent_id is not None:
        result["agent_id"] = base.agent_id
    if base.agent_type is not None:
        result["agent_type"] = base.agent_type
    result.update(extra)
    return result


@dataclass(frozen=True)
class HookResult:
    """单个钩子执行结果。"""

    hook_type: str
    success: bool
    output: str = ""
    # 通用字段
    prevent_continuation: bool = False
    permission_behavior: str | None = None  # "allow" | "deny" | "ask" | None
    blocking_error: str | None = None
    system_message: str | None = None
    hook_specific_output: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # 事件特定字段（由 processHookJSONOutput 按 hookEventName 分发提取）
    additional_context: str | None = None
    updated_input: dict[str, Any] | None = None
    initial_user_message: str | None = None
    watch_paths: list[str] | None = None
    stop_reason: str | None = None


@dataclass(frozen=True)
class AggregatedHookResult:
    """聚合钩子结果。"""

    results: list[HookResult] = field(default_factory=list)

    @property
    def permission_behavior(self) -> str | None:
        """聚合权限行为：deny > ask > allow > None。"""
        behaviors = [r.permission_behavior for r in self.results if r.permission_behavior]
        if "deny" in behaviors:
            return "deny"
        if "ask" in behaviors:
            return "ask"
        if "allow" in behaviors:
            return "allow"
        return None

    @property
    def blocked(self) -> bool:
        return self.permission_behavior == "deny"

    @property
    def reason(self) -> str:
        for r in self.results:
            if r.permission_behavior == "deny":
                return r.blocking_error or r.system_message or r.output
        return ""

    @property
    def system_message(self) -> str | None:
        messages = [r.system_message for r in self.results if r.system_message]
        return "\n".join(messages) if messages else None

    @property
    def hook_specific_output(self) -> dict[str, Any] | None:
        outputs = {}
        for r in self.results:
            if r.hook_specific_output:
                outputs.update(r.hook_specific_output)
        return outputs or None

    @property
    def additional_contexts(self) -> list[str]:
        """收集所有钩子的 additionalContext。"""
        return [r.additional_context for r in self.results if r.additional_context]

    @property
    def updated_input(self) -> dict[str, Any] | None:
        """返回第一个 updatedInput（PreToolUse 钩子可修改工具输入）。"""
        for r in self.results:
            if r.updated_input:
                return r.updated_input
        return None

    @property
    def initial_user_message(self) -> str | None:
        """返回第一个 initialUserMessage（SessionStart 钩子可注入初始消息）。"""
        for r in self.results:
            if r.initial_user_message:
                return r.initial_user_message
        return None

    @property
    def watch_paths(self) -> list[str]:
        """收集所有 watchPaths。"""
        paths = []
        for r in self.results:
            if r.watch_paths:
                paths.extend(r.watch_paths)
        return paths

    @property
    def prevent_continuation(self) -> bool:
        return any(r.prevent_continuation for r in self.results)

    @property
    def stop_reason(self) -> str | None:
        for r in self.results:
            if r.stop_reason:
                return r.stop_reason
        return None
