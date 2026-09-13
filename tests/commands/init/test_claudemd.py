"""CLAUDE.md 生成器测试"""

from pathlib import Path

from illusion_forge.commands.init.generation.claudemd import generate_claude_md, update_claude_md
from illusion_forge.commands.init.generation.sections import has_section
from illusion_forge.commands.init.types import (
    AnalysisResult,
    ConventionInfo,
    ModuleSummary,
    ProjectData,
)


def _make_analysis() -> AnalysisResult:
    """创建测试用分析结果"""
    return AnalysisResult(
        project_name="test-project",
        project_description="A test project for testing.",
        directory_tree="test-project/\n  src/\n    main.py\n  tests/\n  pyproject.toml",
        architecture_notes=["Uses src/ layout"],
        conventions=ConventionInfo(
            naming_style="snake_case",
            import_style="absolute",
            docstring_style="google",
            line_length=88,
            type_hints=True,
            test_framework="pytest",
            test_directory="tests",
        ),
        key_modules=[
            ModuleSummary(
                name="main",
                path="src/main.py",
                description="Entry point",
                key_classes=["App"],
                key_functions=["main", "setup"],
            ),
        ],
        dependency_summary={
            "Web Frameworks": ["flask"],
            "Testing": ["pytest"],
        },
    )


def _make_data() -> ProjectData:
    """创建测试用项目数据"""
    from illusion_forge.commands.init.types import FileInfo
    return ProjectData(
        root=Path("."),
        files=[FileInfo(Path("src/main.py"), "Python", 100)],
        languages={"Python": 10},
        frameworks=["Flask"],
        package_manager="pip",
        build_commands=["make build"],
        test_commands=["pytest"],
        lint_commands=["ruff check"],
        format_commands=["ruff format"],
        ci_config="GitHub Actions",
        readme_summary="A test project.",
        readme_sections={},
        existing_ai_configs=[".cursor/rules"],
        config_files={},
        pyproject_data=None,
        package_json_data=None,
        modules=[],
    )


def test_generate_claude_md_has_all_sections():
    """测试生成的 CLAUDE.md 包含所有章节"""
    analysis = _make_analysis()
    data = _make_data()

    content = generate_claude_md(analysis, data)

    assert "# CLAUDE.md" in content
    assert has_section(content, "overview")
    assert has_section(content, "tech-stack")
    assert has_section(content, "structure")
    assert has_section(content, "key-modules")
    assert has_section(content, "conventions")
    assert has_section(content, "commands")
    assert has_section(content, "dependencies")


def test_generate_claude_md_content_quality():
    """测试生成内容的质量"""
    analysis = _make_analysis()
    data = _make_data()

    content = generate_claude_md(analysis, data)

    assert "A test project for testing." in content
    assert "Python" in content
    assert "Flask" in content
    assert "snake_case" in content
    assert "pytest" in content
    assert "main.py" in content
    assert "App" in content


def test_update_claude_md_preserves_manual_edits():
    """测试更新 CLAUDE.md 保留手动编辑"""
    analysis = _make_analysis()
    data = _make_data()

    # 模拟用户手动添加的内容
    existing = (
        "# My Project\n\n"
        "Custom notes here.\n\n"
        "<!-- ILLUSION:overview START -->\nold overview\n<!-- ILLUSION:overview END -->\n\n"
        "More manual content.\n"
    )

    result = update_claude_md(existing, analysis, data)

    assert "Custom notes here." in result
    assert "More manual content." in result
    assert "old overview" not in result
    assert "A test project for testing." in result


def test_update_claude_md_no_markers():
    """测试更新没有 marker 的 CLAUDE.md"""
    analysis = _make_analysis()
    data = _make_data()

    existing = "# My Project\n\nSome content.\n"
    result = update_claude_md(existing, analysis, data)

    assert "Some content." in result
    assert "A test project for testing." in result
