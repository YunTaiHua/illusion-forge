"""
钩子模块
========

本模块提供 IllusionForge 钩子系统功能。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from illusion_forge.hooks.events import HookEvent
    from illusion_forge.hooks.executor import HookExecutionContext, HookExecutor
    from illusion_forge.hooks.loader import HookRegistry, load_hook_registry
    from illusion_forge.hooks.register_hooks import register_frontmatter_hooks, register_skill_hooks
    from illusion_forge.hooks.schemas import HookMatcherDefinition
    from illusion_forge.hooks.session_hooks import SessionHookStore
    from illusion_forge.hooks.types import AggregatedHookResult, BaseHookInput, HookResult

__all__ = [
    "AggregatedHookResult",
    "BaseHookInput",
    "HookEvent",
    "HookExecutionContext",
    "HookExecutor",
    "HookMatcherDefinition",
    "HookRegistry",
    "HookResult",
    "SessionHookStore",
    "load_hook_registry",
    "register_frontmatter_hooks",
    "register_skill_hooks",
]


def __getattr__(name: str) -> object:
    if name == "HookEvent":
        from illusion_forge.hooks.events import HookEvent
        return HookEvent
    if name in {"HookExecutionContext", "HookExecutor"}:
        from illusion_forge.hooks.executor import HookExecutionContext, HookExecutor
        return {"HookExecutionContext": HookExecutionContext, "HookExecutor": HookExecutor}[name]
    if name in {"HookRegistry", "load_hook_registry"}:
        from illusion_forge.hooks.loader import HookRegistry, load_hook_registry
        return {"HookRegistry": HookRegistry, "load_hook_registry": load_hook_registry}[name]
    if name in {"AggregatedHookResult", "BaseHookInput", "HookResult"}:
        from illusion_forge.hooks.types import AggregatedHookResult, BaseHookInput, HookResult
        return {"AggregatedHookResult": AggregatedHookResult, "BaseHookInput": BaseHookInput, "HookResult": HookResult}[name]
    if name == "HookMatcherDefinition":
        from illusion_forge.hooks.schemas import HookMatcherDefinition
        return HookMatcherDefinition
    if name == "SessionHookStore":
        from illusion_forge.hooks.session_hooks import SessionHookStore
        return SessionHookStore
    if name in {"register_frontmatter_hooks", "register_skill_hooks"}:
        from illusion_forge.hooks.register_hooks import (
            register_frontmatter_hooks,
            register_skill_hooks,
        )
        return {"register_frontmatter_hooks": register_frontmatter_hooks, "register_skill_hooks": register_skill_hooks}[name]
    raise AttributeError(name)
