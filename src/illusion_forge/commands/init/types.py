"""
/init 命令数据类型定义
====================

定义提取、分析、生成各阶段使用的数据结构。

数据流：ProjectData（提取） → AnalysisResult（分析） → 生成各文件
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SymbolInfo:
    """从源文件提取的符号信息"""

    name: str
    kind: str  # "class", "function", "method", "constant", "import"
    line: int
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    signature: str | None = None


@dataclass
class FileInfo:
    """单个源文件的分析结果"""

    path: Path  # 相对于项目根目录的路径
    language: str  # 语言标识
    size: int  # 文件大小（字节）


@dataclass
class ProjectData:
    """提取阶段的原始数据"""

    root: Path
    files: list[FileInfo]
    languages: dict[str, int]  # language -> file count
    frameworks: list[str]
    package_manager: str | None
    build_commands: list[str]
    test_commands: list[str]
    lint_commands: list[str]
    format_commands: list[str]
    ci_config: str | None
    readme_summary: str | None
    readme_sections: dict[str, str]  # heading -> content
    existing_ai_configs: list[str]
    config_files: dict[str, str]  # filename -> content excerpt
    pyproject_data: dict[str, Any] | None
    package_json_data: dict[str, Any] | None
    modules: list[Any]  # list[ModuleInfo] from illusion_forge.services.lsp.types


@dataclass
class ConventionInfo:
    """检测到的编码规范"""

    naming_style: str  # "snake_case", "camelCase", "mixed"
    import_style: str  # "absolute", "relative", "mixed"
    docstring_style: str | None  # "google", "numpy", "sphinx", None
    line_length: int | None
    type_hints: bool  # 是否使用类型注解
    test_framework: str | None
    test_directory: str | None


@dataclass
class ModuleSummary:
    """关键模块摘要"""

    name: str
    path: str
    description: str
    key_classes: list[str]
    key_functions: list[str]


@dataclass
class AnalysisResult:
    """分析阶段的结构化结果"""

    project_name: str
    project_description: str
    directory_tree: str
    architecture_notes: list[str]
    conventions: ConventionInfo
    key_modules: list[ModuleSummary]
    dependency_summary: dict[str, list[str]]  # category -> [packages]
