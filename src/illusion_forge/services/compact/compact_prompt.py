"""
压缩提示词构建与格式化。
"""

from __future__ import annotations

import re

from illusion_forge.services.compact.constants import (
    BASE_COMPACT_PROMPT,
    NO_TOOLS_PREAMBLE,
    NO_TOOLS_TRAILER,
)


def get_compact_prompt(custom_instructions: str | None = None) -> str:
    """构建发送给模型的完整压缩提示词。"""
    prompt = NO_TOOLS_PREAMBLE + BASE_COMPACT_PROMPT
    if custom_instructions and custom_instructions.strip():
        prompt += f"\n\nAdditional Instructions:\n{custom_instructions}"
    prompt += NO_TOOLS_TRAILER
    return prompt


def format_compact_summary(raw_summary: str) -> str:
    """移除 <analysis> 草稿并提取 <summary> 内容。"""
    text = re.sub(r"<analysis>[\s\S]*?</analysis>", "", raw_summary)
    m = re.search(r"<summary>([\s\S]*?)</summary>", text)
    if m:
        text = text.replace(m.group(0), f"Summary:\n{m.group(1).strip()}")
    text = re.sub(r"\n\n+", "\n\n", text)
    return text.strip()


def build_compact_summary_message(
    summary: str,
    *,
    suppress_follow_up: bool = False,
    recent_preserved: bool = False,
) -> str:
    """创建替换压缩历史的消息。"""
    from illusion_forge.config.i18n import t

    formatted = format_compact_summary(summary)
    text = f"{t('compact_summary_prefix')}\n\n{formatted}"
    if recent_preserved:
        text += f"\n\n{t('compact_recent_preserved')}"
    if suppress_follow_up:
        text += t("compact_suppress_followup")
    return text
