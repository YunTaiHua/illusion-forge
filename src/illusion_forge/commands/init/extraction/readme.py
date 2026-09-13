"""
README 解析器
============

解析 README.md 的 markdown 结构，提取项目描述和各章节内容。
跳过 badges、图片、HTML 块、代码块。
"""

from __future__ import annotations

from pathlib import Path


def extract_readme(root: Path) -> tuple[str | None, dict[str, str]]:
    """提取 README 摘要和各章节内容

    Args:
        root: 项目根目录

    Returns:
        (summary_text, {heading: content})，无 README 时返回 (None, {})
    """
    readme = root / "README.md"
    if not readme.exists():
        # 尝试 readme.md（小写）
        readme = root / "readme.md"
    if not readme.exists():
        return None, {}

    try:
        content = readme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, {}

    sections: dict[str, str] = {}
    summary_parts: list[str] = []

    current_heading: str | None = None
    current_lines: list[str] = []
    in_code_block = False
    in_html_block = False
    total_chars = 0
    max_chars = 500

    for line in content.split("\n"):
        stripped = line.strip()

        # 代码块处理
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # HTML 块处理
        if stripped.startswith("<") and not stripped.startswith("</"):
            if stripped.endswith(">") and "/" not in stripped:
                in_html_block = True
            continue
        if in_html_block:
            if stripped.startswith("</") or stripped.endswith("/>"):
                in_html_block = False
            continue

        # 标题行
        if stripped.startswith("#"):
            # 保存上一个章节
            if current_heading and current_lines:
                text = _clean_text(current_lines)
                if text:
                    sections[current_heading] = text

            # 提取标题文本
            heading_text = stripped.lstrip("#").strip()
            if not current_heading and summary_parts:
                # 第一个标题之前的文本作为摘要
                pass
            current_heading = heading_text
            current_lines = []
            continue

        # 跳过图片和 badges
        if stripped.startswith("!["):
            continue
        if stripped.startswith("[") and ("badge" in stripped.lower() or "shield" in stripped.lower()):
            continue

        # 空行
        if not stripped:
            if current_lines:
                current_lines.append("")
            continue

        # 有意义的文本
        if len(stripped) > 5:
            if not current_heading:
                # 标题之前的描述文本
                summary_parts.append(stripped)
            else:
                current_lines.append(stripped)

        total_chars += len(stripped)
        if total_chars >= max_chars:
            break

    # 保存最后一个章节
    if current_heading and current_lines:
        text = _clean_text(current_lines)
        if text:
            sections[current_heading] = text

    # 构建摘要
    summary = None
    if summary_parts:
        summary = " ".join(summary_parts[:3])
        if len(summary) > 300:
            summary = summary[:297] + "..."
    elif sections:
        # 如果没有标题前的描述，取第一个章节的内容
        first_key = next(iter(sections))
        summary = sections[first_key][:300]

    return summary, sections


def _clean_text(lines: list[str]) -> str:
    """清理文本行，去除多余空行"""
    # 去除首尾空行
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    text = "\n".join(lines).strip()
    # 限制长度
    if len(text) > 300:
        text = text[:297] + "..."
    return text
