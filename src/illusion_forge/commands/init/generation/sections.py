"""
Marker 章节管理工具
==================

提供基于标记的章节包裹、替换和检测功能。
允许后续 /init 重新运行时更新自动生成的章节，同时保留用户手动添加的内容。

灵感来源：codegraph 项目的 installer marker 模式。
"""

from __future__ import annotations

MARKER_START = "<!-- ILLUSION:{section} START -->"
MARKER_END = "<!-- ILLUSION:{section} END -->"


def wrap_section(section_name: str, content: str) -> str:
    """用标记包裹内容

    Args:
        section_name: 章节名称
        content: 章节内容

    Returns:
        带标记的章节字符串
    """
    start = MARKER_START.format(section=section_name)
    end = MARKER_END.format(section=section_name)
    return f"{start}\n{content}\n{end}"


def replace_section(existing_content: str, section_name: str, new_content: str) -> str:
    """替换已有标记之间的内容，保留标记外的手动编辑

    如果不存在对应标记，则追加到末尾。

    Args:
        existing_content: 已有文件内容
        section_name: 章节名称
        new_content: 新的章节内容

    Returns:
        替换后的完整内容
    """
    start = MARKER_START.format(section=section_name)
    end = MARKER_END.format(section=section_name)

    start_idx = existing_content.find(start)
    end_idx = existing_content.find(end)

    if start_idx == -1 or end_idx == -1:
        # 标记不存在，追加到末尾
        separator = "\n\n" if existing_content.rstrip() else ""
        return existing_content.rstrip() + separator + wrap_section(section_name, new_content) + "\n"

    # 替换标记之间的内容
    before = existing_content[:start_idx]
    after = existing_content[end_idx + len(end):]
    return before + wrap_section(section_name, new_content) + after


def has_section(content: str, section_name: str) -> bool:
    """检查内容中是否包含指定章节的标记

    Args:
        content: 文件内容
        section_name: 章节名称

    Returns:
        是否包含该章节
    """
    start = MARKER_START.format(section=section_name)
    return start in content
