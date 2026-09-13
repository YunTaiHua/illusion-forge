"""
ILLUSION.md 生成器
==================

生成项目级 ILLUSION.md 指令文件，为 illusion-forge 提供项目特定的 AI 指导。
"""

from __future__ import annotations

from illusion_forge.commands.init.types import AnalysisResult, ProjectData


def generate_illusion_md(analysis: AnalysisResult, data: ProjectData) -> str:
    """生成 ILLUSION.md 内容

    Args:
        analysis: 分析阶段结果
        data: 提取阶段数据

    Returns:
        ILLUSION.md 内容
    """
    sections = [
        "# ILLUSION.md\n",
        f"Project-specific guidance for **{analysis.project_name}**.\n",
        _section_context(analysis),
        _section_architecture(analysis),
        _section_patterns(analysis, data),
        _section_testing(analysis),
        _section_important_files(data),
    ]

    return "\n\n".join(s for s in sections if s)


def _section_context(analysis: AnalysisResult) -> str:
    """项目上下文"""
    if not analysis.project_description:
        return ""

    lines = ["## Project Context\n"]
    lines.append(analysis.project_description)
    return "\n".join(lines)


def _section_architecture(analysis: AnalysisResult) -> str:
    """架构概览"""
    if not analysis.architecture_notes:
        return ""

    lines = ["## Architecture Overview\n"]
    for note in analysis.architecture_notes:
        lines.append(f"- {note}")
    return "\n".join(lines)


def _section_patterns(analysis: AnalysisResult, data: ProjectData) -> str:
    """关键模式"""
    patterns: list[str] = []

    conv = analysis.conventions
    if conv.naming_style == "snake_case":
        patterns.append("Uses snake_case naming convention")
    elif conv.naming_style == "camelCase":
        patterns.append("Uses camelCase naming convention")

    if conv.type_hints:
        patterns.append("Uses Python type hints throughout")

    if conv.docstring_style:
        patterns.append(f"Documented with {conv.docstring_style}-style docstrings")

    if conv.import_style == "relative":
        patterns.append("Prefers relative imports")
    elif conv.import_style == "absolute":
        patterns.append("Uses absolute imports")

    if not patterns:
        return ""

    lines = ["## Key Patterns\n"]
    for p in patterns:
        lines.append(f"- {p}")
    return "\n".join(lines)


def _section_testing(analysis: AnalysisResult) -> str:
    """测试指南"""
    conv = analysis.conventions
    if not conv.test_framework:
        return ""

    lines = ["## Testing Guidelines\n"]
    lines.append(f"- **Framework**: {conv.test_framework}")

    if conv.test_directory:
        lines.append(f"- **Test Location**: `{conv.test_directory}/`")

    # 从命令中找测试命令
    return "\n".join(lines)


def _section_important_files(data: ProjectData) -> str:
    """重要文件"""
    important: list[str] = []

    # 入口文件
    entry_candidates = ["main.py", "app.py", "manage.py", "main.go", "main.rs", "index.ts", "index.js"]
    for candidate in entry_candidates:
        if (data.root / candidate).exists():
            important.append(f"`{candidate}` - entry point")

    # 配置文件
    config_candidates = ["pyproject.toml", "package.json", "Cargo.toml", "go.mod", "Makefile"]
    for candidate in config_candidates:
        if (data.root / candidate).exists():
            important.append(f"`{candidate}` - project configuration")

    if not important:
        return ""

    lines = ["## Important Files\n"]
    for f in important:
        lines.append(f"- {f}")
    return "\n".join(lines)
