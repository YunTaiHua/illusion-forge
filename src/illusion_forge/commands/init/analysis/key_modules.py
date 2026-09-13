"""
关键模块识别器
==============

识别项目中的核心模块：入口点、包含最多类/函数的模块等。
使用统一的 ModuleInfo 数据模型，支持所有语言。
"""

from __future__ import annotations

from pathlib import Path

from illusion_forge.commands.init.types import ModuleSummary, ProjectData
from illusion_forge.services.lsp.types import SymbolKind


def identify_key_modules(data: ProjectData) -> list[ModuleSummary]:
    """识别关键模块

    Args:
        data: 提取阶段的项目数据

    Returns:
        关键模块摘要列表（最多 10 个）
    """
    candidates: list[ModuleSummary] = []

    # 统一分析所有语言的模块
    if data.modules:
        candidates.extend(_analyze_modules(data))

    # 去重并限制数量
    seen_paths: set[str] = set()
    unique: list[ModuleSummary] = []
    for mod in candidates:
        if mod.path not in seen_paths:
            seen_paths.add(mod.path)
            unique.append(mod)

    return unique[:10]


def _analyze_modules(data: ProjectData) -> list[ModuleSummary]:
    """分析所有模块，识别关键模块。"""
    summaries: list[ModuleSummary] = []

    for mod in data.modules:
        classes = [s.name for s in mod.symbols if s.kind == SymbolKind.CLASS]
        functions = [s.name for s in mod.symbols if s.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD)]

        # 包含类或函数的模块才是候选
        if not classes and not functions:
            continue

        # 入口点检测
        is_entry = _is_entry_point(mod.path, data)

        # 构建描述
        description_parts: list[str] = []
        if is_entry:
            description_parts.append("entry point")
        if classes:
            description_parts.append(f"{len(classes)} class(es)")
        if functions:
            description_parts.append(f"{len(functions)} function(s)")
        desc = f"[{mod.language}] {', '.join(description_parts)}" if description_parts else f"[{mod.language}] source module"

        summaries.append(
            ModuleSummary(
                name=mod.path.stem,
                path=str(mod.path),
                description=desc,
                key_classes=classes[:5],
                key_functions=functions[:5],
            )
        )

    # 按重要性排序：入口点 > 符号多的模块
    def _sort_key(m: ModuleSummary) -> tuple[int, int]:
        is_entry = 1 if "entry point" in m.description else 0
        score = len(m.key_classes) + len(m.key_functions)
        return (-is_entry, -score)

    summaries.sort(key=_sort_key)
    return summaries[:10]


def _is_entry_point(path: Path, data: ProjectData) -> bool:
    """检测文件是否为入口点。"""
    name = path.stem

    # 常见入口文件名
    if name in ("main", "index", "app", "cli", "__main__"):
        return True

    # Go cmd/ 目录
    if "cmd" in path.parts and path.suffix == ".go":
        return True

    # pyproject scripts 引用
    if data.pyproject_data:
        scripts = data.pyproject_data.get("project", {}).get("scripts", {})
        poetry_scripts = data.pyproject_data.get("tool", {}).get("poetry", {}).get("scripts", {})
        all_scripts = {**scripts, **poetry_scripts}
        for script_path in all_scripts.values():
            if isinstance(script_path, str) and name in script_path:
                return True

    return False
