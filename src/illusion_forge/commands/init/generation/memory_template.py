"""
MEMORY.md 模板生成器
====================

生成有意义的 user 级记忆目录 MEMORY.md 初始模板（~/.illusion/memory/{项目}-{hash}/），
包含项目概述、架构决策、常用命令等。
"""

from __future__ import annotations

from illusion_forge.commands.init.types import AnalysisResult, ProjectData


def generate_memory_template(analysis: AnalysisResult, data: ProjectData) -> str:
    """生成 MEMORY.md 模板内容

    Args:
        analysis: 分析阶段结果
        data: 提取阶段数据

    Returns:
        MEMORY.md 内容
    """
    sections = [
        f"# Project Memory: {analysis.project_name}\n",
        _section_overview(analysis),
        _section_architecture(analysis),
        _section_commands(analysis, data),
        _section_notes(),
    ]

    return "\n\n".join(s for s in sections if s)


def _section_overview(analysis: AnalysisResult) -> str:
    """项目概述"""
    lines = ["## Overview\n"]
    if analysis.project_description:
        lines.append(analysis.project_description)
    else:
        lines.append(f"Project: {analysis.project_name}")
    return "\n".join(lines)


def _section_architecture(analysis: AnalysisResult) -> str:
    """关键架构决策"""
    if not analysis.architecture_notes:
        return ""

    lines = ["## Key Architecture Decisions\n"]
    for note in analysis.architecture_notes:
        lines.append(f"- {note}")
    return "\n".join(lines)


def _section_commands(analysis: AnalysisResult, data: ProjectData) -> str:
    """常用命令"""
    has_commands = any([
        data.build_commands, data.test_commands,
        data.lint_commands, data.format_commands,
    ])
    if not has_commands:
        return ""

    lines = ["## Frequently Used Commands\n"]

    if data.test_commands:
        lines.append(f"- `{data.test_commands[0]}` - Run tests")
    if data.lint_commands:
        lines.append(f"- `{data.lint_commands[0]}` - Check code style")
    if data.build_commands:
        lines.append(f"- `{data.build_commands[0]}` - Build project")
    if data.format_commands:
        lines.append(f"- `{data.format_commands[0]}` - Format code")

    return "\n".join(lines)


def _section_notes() -> str:
    """用户笔记区"""
    return "## Important Notes\n\n(add project-specific notes here)"
