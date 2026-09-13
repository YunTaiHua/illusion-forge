"""
CLAUDE.md 发现和加载模块
========================

本模块实现 CLAUDE.md 指令文件的发现和加载功能。

主要功能：
    - 在当前目录中查找 CLAUDE.md 文件
    - 发现 .claude/rules 目录下的规则文件
    - 发现 .illusion/ 目录下的指令文件（CLAUDE.md、AGENTS.md、ILLUSION.md）
    - 将多个指令文件加载为一个提示词章节

使用示例：
    >>> from illusion_forge.prompts.claudemd import discover_claude_md_files, load_claude_md_prompt
    >>> files = discover_claude_md_files("/path/to/project")
    >>> prompt = load_claude_md_prompt("/path/to/project")
"""

from __future__ import annotations

from pathlib import Path

# AI 指令文件名列表（在根目录和 .illusion/ 目录下扫描）
_AI_INSTRUCTION_FILES = [
    "CLAUDE.md",
    "AGENTS.md",
    "ILLUSION.md",
]


def discover_claude_md_files(cwd: str | Path) -> list[Path]:
    """发现相关的 CLAUDE.md 指令文件（只在 cwd 中向下查找）

    扫描范围：
    1. 根目录下的 CLAUDE.md、AGENTS.md、ILLUSION.md
    2. .claude/CLAUDE.md 和 .claude/rules/*.md
    3. .illusion/ 目录下的 CLAUDE.md、AGENTS.md、ILLUSION.md

    Args:
        cwd: 工作目录

    Returns:
        list[Path]: 找到的指令文件路径列表
    """
    # 加载项目级权限配置
    from illusion_forge.permissions.loader import load_project_permissions
    project_permissions = load_project_permissions(cwd)

    current = Path(cwd).resolve()
    results: list[Path] = []
    seen: set[Path] = set()

    # 1. 扫描根目录下的 AI 指令文件
    for filename in _AI_INSTRUCTION_FILES:
        candidate = current / filename
        if candidate.exists() and candidate not in seen:
            results.append(candidate)
            seen.add(candidate)

    # 2. 扫描 .claude/ 目录下的文件
    claude_dir = current / ".claude"
    claude_md = claude_dir / "CLAUDE.md"
    if claude_md.exists() and claude_md not in seen:
        results.append(claude_md)
        seen.add(claude_md)

    # 检查是否禁用所有 rules
    from illusion_forge.permissions.loader import filter_rules_by_permissions, is_rules_disabled
    if not is_rules_disabled(project_permissions):
        rules_dir = claude_dir / "rules"
        if rules_dir.is_dir():
            all_rules = sorted(rules_dir.glob("*.md"))
            filtered_rules = filter_rules_by_permissions(all_rules, project_permissions)
            for rule in filtered_rules:
                if rule not in seen:
                    results.append(rule)
                    seen.add(rule)

    # 3. 扫描 .illusion/ 目录下的 AI 指令文件
    illusion_dir = current / ".illusion"
    if illusion_dir.is_dir():
        for filename in _AI_INSTRUCTION_FILES:
            candidate = illusion_dir / filename
            if candidate.exists() and candidate not in seen:
                results.append(candidate)
                seen.add(candidate)

    return results


def load_claude_md_prompt(cwd: str | Path, *, max_chars_per_file: int = 12000) -> str | None:
    """将发现的指令文件加载为一个提示词章节
    
    Args:
        cwd: 工作目录
        max_chars_per_file: 每个文件的最大字符数
    
    Returns:
        str | None: 格式化的提示词章节，如果没有文件则返回 None
    """
    files = discover_claude_md_files(cwd)
    if not files:
        return None

    lines = ["# Project Instructions"]
    for path in files:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars_per_file:
            content = content[:max_chars_per_file] + "\n...[truncated]..."
        lines.extend(["", f"## {path}", "```md", content.strip(), "```"])
    return "\n".join(lines)
