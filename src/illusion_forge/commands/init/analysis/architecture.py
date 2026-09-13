"""
架构分析器
==========

生成项目目录树，检测架构模式（src/ layout、monorepo 等），
分析模块关系识别核心模块。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from illusion_forge.commands.init.types import ProjectData

# 目录树中应忽略的目录
_TREE_IGNORE = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "coverage", ".coverage", "htmlcov", ".eggs",
    ".illusion", ".claude", ".cursor", ".vscode", ".idea",
    ".github", ".gitlab",
})

# 最大目录树深度
_MAX_DEPTH = 3

# 最大每层条目数
_MAX_ENTRIES_PER_LEVEL = 15


def analyze_architecture(data: ProjectData) -> tuple[str, list[str]]:
    """分析项目架构

    Args:
        data: 提取阶段的项目数据

    Returns:
        (directory_tree, architecture_notes)
    """
    tree = _build_directory_tree(data.root)
    notes = _detect_patterns(data)
    return tree, notes


def _build_directory_tree(root: Path, max_depth: int = _MAX_DEPTH) -> str:
    """构建目录树字符串

    Args:
        root: 项目根目录
        max_depth: 最大深度

    Returns:
        格式化的目录树
    """
    lines = [f"{root.name}/"]
    _build_tree_recursive(root, "", max_depth, 0, lines)

    # 如果太长，截断
    if len(lines) > 60:
        lines = lines[:59]
        lines.append("  ...")

    return "\n".join(lines)


def _build_tree_recursive(
    current: Path,
    prefix: str,
    max_depth: int,
    depth: int,
    lines: list[str],
) -> None:
    """递归构建目录树"""
    if depth >= max_depth:
        return

    try:
        entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return

    # 过滤忽略的目录和文件
    filtered = []
    for entry in entries:
        if entry.name in _TREE_IGNORE:
            continue
        if entry.name.startswith(".") and entry.name not in (".env.example",):
            continue
        if entry.suffix in (".pyc", ".pyo", ".class", ".o", ".so", ".dll"):
            continue
        filtered.append(entry)

    # 限制每层条目数
    if len(filtered) > _MAX_ENTRIES_PER_LEVEL:
        shown = filtered[:_MAX_ENTRIES_PER_LEVEL]
        remaining = len(filtered) - _MAX_ENTRIES_PER_LEVEL
    else:
        shown = filtered
        remaining = 0

    for i, entry in enumerate(shown):
        is_last = i == len(shown) - 1 and remaining == 0
        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        if entry.is_dir():
            # 检查目录是否为空（排除忽略的子目录）
            try:
                children = [e for e in entry.iterdir() if e.name not in _TREE_IGNORE]
                if not children:
                    continue
            except OSError:
                continue

            lines.append(f"{prefix}{connector}{entry.name}/")
            _build_tree_recursive(entry, child_prefix, max_depth, depth + 1, lines)
        else:
            lines.append(f"{prefix}{connector}{entry.name}")

    if remaining > 0:
        lines.append(f"{prefix}└── ... ({remaining} more)")


def _detect_patterns(data: ProjectData) -> list[str]:
    """检测架构模式"""
    notes: list[str] = []
    root = data.root

    # src/ layout
    if (root / "src").is_dir():
        notes.append("Uses src/ layout for source code")

    # Flat layout（Python 包直接在根目录）
    py_dirs = [f.path.parent for f in data.files if f.language == "Python" and f.path.parent != Path(".")]
    if py_dirs and not (root / "src").is_dir():
        # 检查根目录是否有 Python 包（有 __init__.py 的目录）
        pkg_dirs = set()
        for d in py_dirs:
            top = d.parts[0] if d.parts else None
            if top and (root / top / "__init__.py").exists():
                pkg_dirs.add(top)
        if pkg_dirs:
            notes.append(f"Python flat layout with packages: {', '.join(sorted(pkg_dirs))}")

    # Go layout
    if (root / "cmd").is_dir():
        notes.append("Go cmd/ layout for CLI entry points")
    if (root / "internal").is_dir():
        notes.append("Go internal/ layout for private packages")

    # Monorepo
    if (root / "packages").is_dir() or (root / "apps").is_dir():
        notes.append("Monorepo structure (packages/ or apps/)")

    # Web app patterns
    if (root / "app").is_dir() and (root / "routes").is_dir():
        notes.append("Web app with app/routes structure")

    # lib/ + bin/
    if (root / "lib").is_dir() and (root / "bin").is_dir():
        notes.append("lib/ + bin/ structure")

    # Module relationships（基于符号数量分析）
    if data.modules:
        from illusion_forge.services.lsp.types import SymbolKind

        symbol_counts: Counter[str] = Counter()
        for mod in data.modules:
            count = len([s for s in mod.symbols if s.kind in (SymbolKind.CLASS, SymbolKind.FUNCTION, SymbolKind.METHOD)])
            if count > 0:
                symbol_counts[str(mod.path.stem)] += count

        if symbol_counts:
            core_modules = [name for name, _ in symbol_counts.most_common(3)]
            if core_modules:
                notes.append(f"Core modules (most symbols): {', '.join(core_modules)}")

    return notes
