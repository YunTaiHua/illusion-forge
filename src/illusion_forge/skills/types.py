"""
Skill 数据模型模块
================

SKILL.md frontmatter 字段数据模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SkillDefinition:
    """已加载的 Skill。"""

    name: str
    description: str
    content: str
    source: str
    path: str | None = None

    allowed_tools: list[str] | None = None
    model: str | None = None
    hooks: dict[str, list[Any]] | None = None
    context: str | None = None  # "inline" | "fork"
    agent: str | None = None
    disable_model_invocation: bool | None = None
    effort: str | None = None
    skill_root: str | None = None
