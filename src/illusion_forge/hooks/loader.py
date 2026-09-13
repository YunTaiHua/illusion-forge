"""
钩子加载器模块
==============

从设置和插件加载钩子注册表。
格式：{ "PreToolUse": [{ "matcher": "Bash", "hooks": [...] }] }
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from illusion_forge.hooks.events import HookEvent
from illusion_forge.hooks.schemas import (
    HookDefinition,
    HookMatcherDefinition,
    parse_hook_definition,
)


class HookRegistry:
    """钩子注册表，按事件存储 HookMatcherDefinition 列表。"""

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[HookMatcherDefinition]] = defaultdict(list)

    def register(self, event: HookEvent, matcher: HookMatcherDefinition) -> None:
        """注册一个钩子匹配器。"""
        self._hooks[event].append(matcher)

    def register_hook(self, event: HookEvent, hook: HookDefinition, matcher: str = "") -> None:
        """注册单个钩子（便捷方法）。"""
        self._hooks[event].append(HookMatcherDefinition(matcher=matcher, hooks=[hook]))

    def get(self, event: HookEvent) -> list[HookMatcherDefinition]:
        """获取指定事件的所有匹配器。"""
        return list(self._hooks.get(event, []))

    def get_hooks_flat(self, event: HookEvent) -> list[HookDefinition]:
        """获取指定事件的所有钩子（扁平列表）。"""
        hooks = []
        for matcher in self.get(event):
            hooks.extend(matcher.hooks)
        return hooks

    def summary(self) -> str:
        """生成人类可读的钩子摘要。"""
        lines: list[str] = []
        for event in HookEvent:
            matchers = self.get(event)
            if not matchers:
                continue
            lines.append(f"{event.value}:")
            for m in matchers:
                for hook in m.hooks:
                    detail = getattr(hook, "command", None) or getattr(hook, "prompt", None) or getattr(hook, "url", None) or ""
                    suffix = f" matcher={m.matcher}" if m.matcher else ""
                    lines.append(f"  - {hook.type}{suffix}: {detail}")
        return "\n".join(lines)


def _normalize_hooks_value(value: Any) -> list[HookMatcherDefinition]:
    """将 hooks 值规范化为 HookMatcherDefinition 列表。

    格式：list[{ matcher?: string, hooks: HookCommand[] }]
    """
    if not isinstance(value, list):
        return []
    result: list[HookMatcherDefinition] = []
    for item in value:
        if not isinstance(item, dict) or "hooks" not in item:
            continue
        hooks: list[HookDefinition] = []
        for h in item.get("hooks", []):
            if isinstance(h, dict):
                try:
                    hooks.append(parse_hook_definition(h))
                except ValueError:
                    continue
        result.append(HookMatcherDefinition(
            matcher=item.get("matcher", ""),
            hooks=hooks,
        ))
    return result


def load_hook_registry(settings: Any, plugins: Any = None, cwd: str | Path | None = None) -> HookRegistry:
    """从设置对象加载钩子注册表。

    事件名必须是 PascalCase（如 PreToolUse）。
    格式必须是 matcher 结构：[{ "matcher": "...", "hooks": [...] }]
    """
    registry = HookRegistry()

    # 加载项目级权限配置
    from illusion_forge.permissions.loader import load_project_permissions
    project_permissions = load_project_permissions(cwd) if cwd else None

    # 检查是否禁用所有 hooks
    if project_permissions and "*" in project_permissions.denied_hooks:
        return registry

    for raw_event, hooks_value in settings.hooks.items():
        try:
            event = HookEvent(str(raw_event))
        except ValueError:
            continue

        # 检查是否禁用特定事件的 hooks
        if project_permissions and event.value in project_permissions.denied_hooks:
            continue

        for matcher_def in _normalize_hooks_value(hooks_value):
            registry.register(event, matcher_def)

    for plugin in plugins or []:
        if not plugin.enabled:
            continue
        for raw_event, hooks_value in plugin.hooks.items():
            try:
                event = HookEvent(str(raw_event))
            except ValueError:
                continue

            # 检查是否禁用特定事件的 hooks
            if project_permissions and event.value in project_permissions.denied_hooks:
                continue

            for matcher_def in _normalize_hooks_value(hooks_value):
                registry.register(event, matcher_def)

    return registry
