"""
Frontmatter 钩子注册
====================

从 agent/skill 的 frontmatter 中注册会话钩子。
"""

from __future__ import annotations

from illusion_forge.hooks.events import HookEvent
from illusion_forge.hooks.schemas import HookMatcherDefinition
from illusion_forge.hooks.session_hooks import SessionHookStore


def register_frontmatter_hooks(
    store: SessionHookStore,
    session_id: str,
    hooks_settings: dict[str, list[HookMatcherDefinition]],
    source_name: str,
    is_agent: bool = False,
) -> None:
    """从 frontmatter 注册钩子到会话。

    当 is_agent=True 时，将 Stop 事件转换为 SubagentStop（因为子代理触发的是 SubagentStop）。
    """
    for event_name, matchers in hooks_settings.items():
        try:
            event = HookEvent(event_name)
        except ValueError:
            continue
        target_event = event
        if is_agent and event == HookEvent.STOP:
            target_event = HookEvent.SUBAGENT_STOP
        for matcher_def in matchers:
            for hook in matcher_def.hooks:
                store.add(session_id, target_event, matcher_def.matcher, hook)


def register_skill_hooks(
    store: SessionHookStore,
    session_id: str,
    hooks_settings: dict[str, list[HookMatcherDefinition]],
    skill_name: str,
    skill_root: str | None = None,
) -> None:
    """从 skill frontmatter 注册钩子到会话。"""
    for event_name, matchers in hooks_settings.items():
        try:
            event = HookEvent(event_name)
        except ValueError:
            continue
        for matcher_def in matchers:
            for hook in matcher_def.hooks:
                store.add(session_id, event, matcher_def.matcher, hook, skill_root=skill_root)
