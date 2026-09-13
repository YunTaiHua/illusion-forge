"""
会话钩子管理
============

管理会话级钩子（内存中，会话结束时清除）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from illusion_forge.hooks.events import HookEvent
from illusion_forge.hooks.schemas import HookDefinition


@dataclass
class SessionHookMatcher:
    """会话钩子匹配器。"""

    matcher: str
    skill_root: str | None = None
    hooks: list[HookDefinition] = field(default_factory=list[Any])


@dataclass
class SessionStore:
    """单个会话的钩子存储。"""

    hooks: dict[HookEvent, list[SessionHookMatcher]] = field(default_factory=dict)


class SessionHookStore:
    """会话钩子管理器。"""

    def __init__(self) -> None:
        self._stores: dict[str, SessionStore] = {}

    def add(
        self,
        session_id: str,
        event: HookEvent,
        matcher: str,
        hook: HookDefinition,
        skill_root: str | None = None,
    ) -> None:
        """添加钩子到会话。"""
        store = self._stores.setdefault(session_id, SessionStore())
        event_matchers = store.hooks.setdefault(event, [])
        # 查找已有的 matcher
        for sm in event_matchers:
            if sm.matcher == matcher and sm.skill_root == skill_root:
                sm.hooks.append(hook)
                return
        # 创建新 matcher
        event_matchers.append(
            SessionHookMatcher(matcher=matcher, skill_root=skill_root, hooks=[hook])
        )

    def remove(
        self,
        session_id: str,
        event: HookEvent,
        hook: HookDefinition,
    ) -> None:
        """从会话移除钩子。"""
        store = self._stores.get(session_id)
        if not store:
            return
        event_matchers = store.hooks.get(event, [])
        for sm in event_matchers:
            sm.hooks = [h for h in sm.hooks if not _hooks_equal(h, hook)]
        # 清除空 matcher
        store.hooks[event] = [sm for sm in event_matchers if sm.hooks]
        if not store.hooks.get(event):
            store.hooks.pop(event, None)

    def get(
        self,
        session_id: str,
        event: HookEvent | None = None,
    ) -> dict[HookEvent, list[SessionHookMatcher]] | list[SessionHookMatcher]:
        """获取会话钩子。

        指定 event 时返回该事件的 SessionHookMatcher 列表。
        不指定 event 时返回 {HookEvent: [SessionHookMatcher]} 字典。
        """
        store = self._stores.get(session_id)
        if not store:
            return [] if event is not None else {}
        if event is not None:
            return list(store.hooks.get(event, []))
        return dict(store.hooks)

    def clear(self, session_id: str) -> None:
        """清除会话所有钩子。"""
        self._stores.pop(session_id, None)


def _hooks_equal(a: HookDefinition, b: HookDefinition) -> bool:
    """比较两个钩子定义是否相等（基于类型和关键字段）。"""
    if type(a) is not type(b):
        return False
    a_cmd = getattr(a, "command", None)
    b_cmd = getattr(b, "command", None)
    if a_cmd is not None and b_cmd is not None:
        return bool(a_cmd == b_cmd)
    a_prompt = getattr(a, "prompt", None)
    b_prompt = getattr(b, "prompt", None)
    if a_prompt is not None and b_prompt is not None:
        return bool(a_prompt == b_prompt)
    a_url = getattr(a, "url", None)
    b_url = getattr(b, "url", None)
    if a_url is not None and b_url is not None:
        return bool(a_url == b_url)
    return False
