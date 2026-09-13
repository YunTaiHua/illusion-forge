"""
CLAUDE.md 生成器
================

生成高质量的 CLAUDE.md 文件，包含项目概述、技术栈、目录结构、
关键模块、编码规范、常用命令、依赖分析等章节。

每个章节用 marker 包裹，支持后续 /init 重新运行时更新。
"""

from __future__ import annotations

from illusion_forge.commands.init.generation.sections import replace_section, wrap_section
from illusion_forge.commands.init.types import AnalysisResult, ProjectData


def generate_claude_md(analysis: AnalysisResult, data: ProjectData) -> str:
    """生成 CLAUDE.md 内容

    Args:
        analysis: 分析阶段结果
        data: 提取阶段数据

    Returns:
        完整的 CLAUDE.md 内容
    """
    sections = [
        "# CLAUDE.md\n",
        _section_overview(analysis),
        _section_tech_stack(analysis, data),
        _section_structure(analysis),
        _section_key_modules(analysis),
        _section_conventions(analysis),
        _section_commands(data),
        _section_dependencies(analysis),
        _section_ai_configs(data),
    ]

    return "\n".join(sections)


def update_claude_md(existing: str, analysis: AnalysisResult, data: ProjectData) -> str:
    """更新已有 CLAUDE.md，保留 marker 外的手动编辑

    Args:
        existing: 已有文件内容
        analysis: 分析阶段结果
        data: 提取阶段数据

    Returns:
        更新后的 CLAUDE.md 内容
    """
    content = existing

    # 更新各章节
    content = replace_section(content, "overview", _overview_body(analysis))
    content = replace_section(content, "tech-stack", _tech_stack_body(analysis, data))
    content = replace_section(content, "structure", _structure_body(analysis))
    content = replace_section(content, "key-modules", _key_modules_body(analysis))
    content = replace_section(content, "conventions", _conventions_body(analysis))
    content = replace_section(content, "commands", _commands_body(data))
    content = replace_section(content, "dependencies", _dependencies_body(analysis))
    content = replace_section(content, "ai-configs", _ai_configs_body(data))

    return content


# --- 各章节生成 ---

def _section_overview(analysis: AnalysisResult) -> str:
    body = _overview_body(analysis)
    return wrap_section("overview", body)


def _overview_body(analysis: AnalysisResult) -> str:
    lines = ["## Project Overview\n"]
    if analysis.project_description:
        lines.append(analysis.project_description)
    else:
        lines.append(f"Project: {analysis.project_name}")
    return "\n".join(lines)


def _section_tech_stack(analysis: AnalysisResult, data: ProjectData) -> str:
    body = _tech_stack_body(analysis, data)
    return wrap_section("tech-stack", body)


def _tech_stack_body(analysis: AnalysisResult, data: ProjectData) -> str:
    lines = ["## Tech Stack\n"]

    if data.languages:
        lang_strs = [f"{lang} ({count} files)" for lang, count in data.languages.items()]
        lines.append(f"- **Languages**: {', '.join(lang_strs)}")

    if data.frameworks:
        lines.append(f"- **Frameworks**: {', '.join(data.frameworks)}")

    if data.package_manager:
        lines.append(f"- **Package Manager**: {data.package_manager}")

    if data.ci_config:
        lines.append(f"- **CI/CD**: {data.ci_config}")

    return "\n".join(lines)


def _section_structure(analysis: AnalysisResult) -> str:
    body = _structure_body(analysis)
    return wrap_section("structure", body)


def _structure_body(analysis: AnalysisResult) -> str:
    lines = ["## Project Structure\n"]
    lines.append("```")
    lines.append(analysis.directory_tree)
    lines.append("```")

    if analysis.architecture_notes:
        lines.append("")
        for note in analysis.architecture_notes:
            lines.append(f"- {note}")

    return "\n".join(lines)


def _section_key_modules(analysis: AnalysisResult) -> str:
    body = _key_modules_body(analysis)
    return wrap_section("key-modules", body)


def _key_modules_body(analysis: AnalysisResult) -> str:
    if not analysis.key_modules:
        return "## Key Modules\n\nNo key modules detected."

    lines = ["## Key Modules\n"]

    for mod in analysis.key_modules:
        lines.append(f"### `{mod.name}`")
        lines.append(f"- **Path**: `{mod.path}`")
        lines.append(f"- **Description**: {mod.description}")
        if mod.key_classes:
            lines.append(f"- **Key Classes**: {', '.join(f'`{c}`' for c in mod.key_classes)}")
        if mod.key_functions:
            lines.append(f"- **Key Functions**: {', '.join(f'`{f}`' for f in mod.key_functions)}")
        lines.append("")

    return "\n".join(lines)


def _section_conventions(analysis: AnalysisResult) -> str:
    body = _conventions_body(analysis)
    return wrap_section("conventions", body)


def _conventions_body(analysis: AnalysisResult) -> str:
    conv = analysis.conventions
    lines = ["## Coding Conventions\n"]

    lines.append(f"- **Naming Style**: {conv.naming_style}")
    lines.append(f"- **Import Style**: {conv.import_style}")

    if conv.docstring_style:
        lines.append(f"- **Docstring Style**: {conv.docstring_style}")

    lines.append(f"- **Type Hints**: {'yes' if conv.type_hints else 'no'}")

    if conv.line_length:
        lines.append(f"- **Line Length**: {conv.line_length}")

    if conv.test_framework:
        lines.append(f"- **Test Framework**: {conv.test_framework}")

    if conv.test_directory:
        lines.append(f"- **Test Directory**: `{conv.test_directory}/`")

    return "\n".join(lines)


def _section_commands(data: ProjectData) -> str:
    body = _commands_body(data)
    return wrap_section("commands", body)


def _commands_body(data: ProjectData) -> str:
    lines = ["## Common Commands\n"]

    has_commands = any([
        data.build_commands, data.test_commands,
        data.lint_commands, data.format_commands,
    ])

    if not has_commands:
        lines.append("No common commands detected.")
        return "\n".join(lines)

    if data.build_commands:
        lines.append(f"- **Build**: `{data.build_commands[0]}`")
    if data.test_commands:
        lines.append(f"- **Test**: `{data.test_commands[0]}`")
    if data.lint_commands:
        lines.append(f"- **Lint**: `{data.lint_commands[0]}`")
    if data.format_commands:
        lines.append(f"- **Format**: `{data.format_commands[0]}`")

    return "\n".join(lines)


def _section_dependencies(analysis: AnalysisResult) -> str:
    body = _dependencies_body(analysis)
    return wrap_section("dependencies", body)


def _dependencies_body(analysis: AnalysisResult) -> str:
    if not analysis.dependency_summary:
        return "## Dependencies\n\nNo dependency analysis available."

    lines = ["## Dependencies\n"]

    for category, packages in analysis.dependency_summary.items():
        lines.append(f"- **{category}**: {', '.join(f'`{p}`' for p in packages)}")

    return "\n".join(lines)


def _section_ai_configs(data: ProjectData) -> str:
    body = _ai_configs_body(data)
    return wrap_section("ai-configs", body)


def _ai_configs_body(data: ProjectData) -> str:
    if not data.existing_ai_configs:
        return ""

    lines = ["## Existing AI Configs\n"]
    lines.append("The following AI configuration files were detected:")
    for config in data.existing_ai_configs:
        lines.append(f"- `{config}`")

    return "\n".join(lines)
