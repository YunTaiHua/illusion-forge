"""
规则文件生成器
==============

自动检测项目模式并生成 .illusion/rules/ 目录下的规则文件。
每个文件包含简短、可操作的开发指导。
"""

from __future__ import annotations

from illusion_forge.commands.init.types import AnalysisResult, ProjectData


def generate_rules(analysis: AnalysisResult, data: ProjectData) -> dict[str, str]:
    """生成规则文件

    Args:
        analysis: 分析阶段结果
        data: 提取阶段数据

    Returns:
        {filename: content} 的映射
    """
    rules: dict[str, str] = {}

    # Python 风格规则
    if "Python" in data.languages:
        content = _rule_python_style(analysis)
        if content:
            rules["python-style.md"] = content

    # 测试规则
    if analysis.conventions.test_framework:
        rules["testing.md"] = _rule_testing(analysis)

    # 项目结构规则
    rules["project-structure.md"] = _rule_project_structure(analysis, data)

    return rules


def _rule_python_style(analysis: AnalysisResult) -> str | None:
    """生成 Python 风格规则"""
    conv = analysis.conventions
    lines = ["# Python Style Guide\n"]

    lines.append(f"- Naming: {conv.naming_style}")
    lines.append(f"- Imports: {conv.import_style}")

    if conv.docstring_style:
        lines.append(f"- Docstrings: {conv.docstring_style} style")
    else:
        lines.append("- Docstrings: add docstrings to public classes and functions")

    if conv.type_hints:
        lines.append("- Type hints: use type annotations for function signatures")
    else:
        lines.append("- Type hints: consider adding type annotations")

    if conv.line_length:
        lines.append(f"- Line length: max {conv.line_length} characters")

    return "\n".join(lines)


def _rule_testing(analysis: AnalysisResult) -> str:
    """生成测试规则"""
    conv = analysis.conventions
    lines = ["# Testing Guide\n"]

    lines.append(f"- Framework: {conv.test_framework}")

    if conv.test_directory:
        lines.append(f"- Location: `{conv.test_directory}/`")
        lines.append("- Naming: test files should be named `test_*.py` or `*_test.py`")

    lines.append(f"- Run tests: `{analysis.project_name} test` or check Common Commands in CLAUDE.md")

    lines.append("\nGuidelines:")
    lines.append("- Write tests for new features and bug fixes")
    lines.append("- Keep tests focused and independent")
    lines.append("- Use descriptive test names that explain the scenario")

    return "\n".join(lines)


def _rule_project_structure(analysis: AnalysisResult, data: ProjectData) -> str:
    """生成项目结构规则"""
    lines = ["# Project Structure Guide\n"]

    if analysis.architecture_notes:
        for note in analysis.architecture_notes:
            lines.append(f"- {note}")
        lines.append("")

    # 模块组织建议
    if data.modules:
        # 检测是否使用 src/ layout
        has_src = any("src" in str(mod.path) for mod in data.modules)
        if has_src:
            lines.append("- Source code lives under `src/`")
        else:
            lines.append("- Source code uses flat layout (packages at project root)")

    lines.append("\nWhen adding new files:")
    lines.append("- Follow the existing directory structure")
    lines.append("- Place tests in the test directory matching the source path")
    lines.append("- Update imports and __init__.py files as needed")

    return "\n".join(lines)
