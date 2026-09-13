"""
编码规范检测
============

从项目源码和配置中检测编码规范：命名风格、导入风格、docstring 风格、
类型注解使用、行长度、测试框架等。
"""

from __future__ import annotations

import re

from illusion_forge.commands.init.types import ConventionInfo, ProjectData


def detect_conventions(data: ProjectData) -> ConventionInfo:
    """检测项目编码规范

    Args:
        data: 提取阶段的项目数据

    Returns:
        检测到的编码规范
    """
    naming = _detect_naming_style(data)
    import_style = _detect_import_style(data)
    docstring_style = _detect_docstring_style(data)
    line_length = _detect_line_length(data)
    type_hints = _detect_type_hints(data)
    test_framework = _detect_test_framework(data)
    test_directory = _detect_test_directory(data)

    return ConventionInfo(
        naming_style=naming,
        import_style=import_style,
        docstring_style=docstring_style,
        line_length=line_length,
        type_hints=type_hints,
        test_framework=test_framework,
        test_directory=test_directory,
    )


def _detect_naming_style(data: ProjectData) -> str:
    """检测命名风格：snake_case / camelCase / mixed"""
    from illusion_forge.services.lsp.types import SymbolKind

    snake = 0
    camel = 0

    for mod in data.modules:
        for sym in mod.symbols:
            if sym.kind not in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                continue
            name = sym.name
            if name.startswith("_"):
                name = name.lstrip("_")
            if "_" in name and name == name.lower():
                snake += 1
            elif name[0].islower() and any(c.isupper() for c in name):
                camel += 1

    total = snake + camel
    if total < 5:
        return _detect_naming_from_filenames(data)

    if snake / total >= 0.8:
        return "snake_case"
    if camel / total >= 0.8:
        return "camelCase"
    return "mixed"


def _detect_naming_from_filenames(data: ProjectData) -> str:
    """从文件名推断命名风格"""
    snake = 0
    camel = 0
    for f in data.files:
        name = f.path.stem
        if "_" in name:
            snake += 1
        elif name[0].islower() and any(c.isupper() for c in name):
            camel += 1

    if snake > camel:
        return "snake_case"
    if camel > snake:
        return "camelCase"
    return "mixed"


def _detect_import_style(data: ProjectData) -> str:
    """检测导入风格：absolute / relative / mixed"""
    relative = 0
    absolute = 0

    for mod in data.modules:
        for imp in mod.imports:
            if imp.startswith("."):
                relative += 1
            else:
                absolute += 1

    total = relative + absolute
    if total < 5:
        return "absolute"

    if relative / total >= 0.7:
        return "relative"
    if absolute / total >= 0.7:
        return "absolute"
    return "mixed"


def _detect_docstring_style(data: ProjectData) -> str | None:
    """检测 docstring 风格（从配置文件推断）"""
    # 从 pyproject.toml 或配置文件推断
    pyproject = data.pyproject_data
    if pyproject:
        tool = pyproject.get("tool", {})
        # ruff 使用 numpy docstring
        if tool.get("ruff", {}).get("docstring-code-line-length"):
            return "numpy"
    return None


def _detect_type_hints(data: ProjectData) -> bool:
    """检测是否广泛使用类型注解（从配置推断）"""
    pyproject = data.pyproject_data
    if pyproject:
        # mypy/pyright 配置暗示使用类型注解
        tool = pyproject.get("tool", {})
        if "mypy" in tool or "pyright" in tool:
            return True
    return False


def _detect_line_length(data: ProjectData) -> int | None:
    """从配置文件检测行长度限制"""
    pyproject = data.pyproject_data
    if pyproject:
        tool = pyproject.get("tool", {})
        # ruff
        ruff_line = tool.get("ruff", {}).get("line-length")
        if ruff_line:
            return int(ruff_line)
        # black
        black_line = tool.get("black", {}).get("line-length")
        if black_line:
            return int(black_line)

    # .editorconfig
    editorconfig = data.root / ".editorconfig"
    if editorconfig.exists():
        try:
            content = editorconfig.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"max_line_length\s*=\s*(\d+)", content)
            if match:
                return int(match.group(1))
        except OSError:
            pass

    # eslint
    for config_name in [".eslintrc.json", ".eslintrc.js", "eslint.config.js"]:
        config = data.config_files.get(config_name)
        if config and "max-len" in config:
            match = re.search(r"max-len.*?(\d+)", config)
            if match:
                return int(match.group(1))

    return None


def _detect_test_framework(data: ProjectData) -> str | None:
    """检测测试框架"""
    # 从 pyproject.toml 检测
    pyproject = data.pyproject_data
    if pyproject:
        all_deps = set()
        # PEP 621
        for dep in pyproject.get("project", {}).get("dependencies", []):
            all_deps.add(dep.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip().lower())
        # Poetry
        poetry_deps = pyproject.get("tool", {}).get("poetry", {}).get("dependencies", {})
        all_deps.update(d.lower() for d in poetry_deps)

        if "pytest" in all_deps:
            return "pytest"
        if "unittest" in str(pyproject):
            return "unittest"

    # 从 package.json 检测
    package_json = data.package_json_data
    if package_json:
        deps = {
            **package_json.get("dependencies", {}),
            **package_json.get("devDependencies", {}),
        }
        if "jest" in deps or "@jest/core" in deps:
            return "jest"
        if "vitest" in deps:
            return "vitest"
        if "mocha" in deps:
            return "mocha"
        if "@playwright/test" in deps:
            return "playwright"
        if "cypress" in deps:
            return "cypress"

    # 从 Makefile 命令检测
    if "pytest" in data.test_commands:
        return "pytest"
    if any("jest" in cmd for cmd in data.test_commands):
        return "jest"
    if any("vitest" in cmd for cmd in data.test_commands):
        return "vitest"

    return None


def _detect_test_directory(data: ProjectData) -> str | None:
    """检测测试目录"""
    candidates = ["tests", "test", "__tests__", "spec", "specs"]
    for candidate in candidates:
        if (data.root / candidate).is_dir():
            return candidate
        # 检查是否有 test_ 开头的文件在根目录
    for f in data.files:
        if f.path.name.startswith("test_"):
            return str(f.path.parent) if str(f.path.parent) != "." else None
    return None
