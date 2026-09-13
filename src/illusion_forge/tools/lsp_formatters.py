"""
LSP 结果格式化函数
==================

将各种 LSP 操作的原始结果转换为人类可读的文本格式。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


def resolve_path(base: Path, candidate: str) -> Path:
    """解析相对路径为绝对路径。"""
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def display_path(path: Path, root: Path) -> str:
    """将路径显示为相对于根目录的路径。"""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def format_go_to_definition(results: list[dict[str, Any]], root: Path) -> str:
    """格式化跳转定义结果。"""
    if not results:
        return "No definition found."
    if len(results) == 1:
        loc = results[0]
        uri = loc.get("uri", "")
        range_ = loc.get("range", loc.get("targetRange", {}))
        start = range_.get("start", {})
        path = _uri_to_path(uri)
        return (
            f"Defined in {display_path(path, root)}:"
            f"{start.get('line', 0) + 1}:{start.get('character', 0) + 1}"
        )
    lines = [f"Found {len(results)} definitions:"]
    for loc in results:
        uri = loc.get("uri", "")
        range_ = loc.get("range", loc.get("targetRange", {}))
        start = range_.get("start", {})
        path = _uri_to_path(uri)
        lines.append(f"  {display_path(path, root)}:{start.get('line', 0) + 1}:{start.get('character', 0) + 1}")
    return "\n".join(lines)


def format_find_references(results: list[dict[str, Any]], root: Path) -> str:
    """格式化查找引用结果，按文件分组。"""
    if not results:
        return "No references found."

    by_file: dict[str, list[int]] = {}
    for loc in results:
        uri = loc.get("uri", "")
        range_ = loc.get("range", {})
        start = range_.get("start", {})
        path = display_path(_uri_to_path(uri), root)
        by_file.setdefault(path, []).append(start.get("line", 0) + 1)

    lines = [f"Found {len(results)} references across {len(by_file)} file(s):"]
    for fp, line_nums in by_file.items():
        lines.append(f"\n{fp}:")
        for ln in line_nums:
            lines.append(f"  Line {ln}")
    return "\n".join(lines)


def format_hover(result: dict[str, Any] | None, root: Path) -> str:
    """格式化悬停结果。"""
    if result is None:
        return "No hover information available."

    contents = result.get("contents", {})
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return str(contents.get("value", str(contents)))
    if isinstance(contents, list):
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("value", str(item)))
        return "\n".join(parts)
    return str(contents)


def format_document_symbol(results: list[dict[str, Any]], root: Path, indent: int = 0) -> str:
    """格式化文档符号结果（层级结构）。"""
    if not results:
        return "(no symbols)"

    lines: list[str] = []
    if indent == 0:
        lines.append("Symbols:")

    for sym in results:
        name = sym.get("name", "")
        if not name or name.startswith("<"):
            continue
        kind_name = _symbol_kind_name(sym.get("kind", 0))
        range_ = sym.get("range", {})
        start = range_.get("start", {})
        prefix = "  " * (indent + 1)
        lines.append(f"{prefix}{kind_name} {name} (line {start.get('line', 0) + 1})")
        children = sym.get("children", [])
        if children:
            lines.append(format_document_symbol(children, root, indent + 1))

    return "\n".join(lines)


def format_workspace_symbol(results: list[dict[str, Any]], root: Path) -> str:
    """格式化工作区符号搜索结果，按文件分组。"""
    if not results:
        return "(no results)"

    by_file: dict[str, list[str]] = {}
    for sym in results:
        name = sym.get("name", "")
        if not name or name.startswith("<"):
            continue
        location = sym.get("location", {})
        uri = location.get("uri", "")
        path = display_path(_uri_to_path(uri), root)
        kind_name = _symbol_kind_name(sym.get("kind", 0))
        container = sym.get("containerName", "")
        label = f"{kind_name} {name}"
        if container:
            label = f"{container}.{label}"
        by_file.setdefault(path, []).append(label)

    total = sum(len(v) for v in by_file.values())
    lines = [f"Found {total} symbol(s) across {len(by_file)} file(s):"]
    for fp, symbols in by_file.items():
        lines.append(f"\n{fp}:")
        for s in symbols:
            lines.append(f"  {s}")
    return "\n".join(lines)


def format_prepare_call_hierarchy(results: list[dict[str, Any]], root: Path) -> str:
    """格式化调用层级准备结果。"""
    if not results:
        return "(no call hierarchy item)"
    item = results[0]
    kind_name = _symbol_kind_name(item.get("kind", 0))
    name = item.get("name", "")
    uri = item.get("uri", "")
    range_ = item.get("range", {})
    start = range_.get("start", {})
    path = display_path(_uri_to_path(uri), root)
    detail = item.get("detail", "")
    parts = [
        f"{kind_name} {name}",
        f"path: {path}:{start.get('line', 0) + 1}:{start.get('character', 0) + 1}",
    ]
    if detail:
        parts.append(f"detail: {detail}")
    return "\n".join(parts)


def format_incoming_calls(results: list[dict[str, Any]], root: Path) -> str:
    """格式化入向调用结果。"""
    if not results:
        return "No incoming calls found (nothing calls this function)."

    # 去重：用 (caller_path, call_line, caller_name) 作为唯一键
    seen: set[tuple[str, int, str]] = set()
    lines: list[str] = []
    for call in results:
        from_ = call.get("from", {})
        from_name = from_.get("name", "")
        from_uri = from_.get("uri", "")
        from_range = from_.get("range", {})
        from_start = from_range.get("start", {})
        from_path = display_path(_uri_to_path(from_uri), root)
        from_ranges = call.get("fromRanges", [])
        for r in from_ranges:
            r_line = r.get("start", {}).get("line", 0) + 1
            key = (from_path, r_line, from_name)
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"  {from_path}:{r_line} [{from_name}] "
                f"(defined at {from_path}:{from_start.get('line', 0) + 1})"
            )
    if not lines:
        return "No incoming calls found (nothing calls this function)."
    return f"Found {len(lines)} incoming call(s):\n" + "\n".join(lines)


def format_outgoing_calls(results: list[dict[str, Any]], root: Path) -> str:
    """格式化出向调用结果。"""
    if not results:
        return "No outgoing calls found (this function calls nothing)."

    seen: set[tuple[str, int, str]] = set()
    lines: list[str] = []
    for call in results:
        to = call.get("to", {})
        to_name = to.get("name", "")
        to_uri = to.get("uri", "")
        to_range = to.get("range", {})
        to_start = to_range.get("start", {})
        to_path = display_path(_uri_to_path(to_uri), root)
        from_ranges = call.get("fromRanges", [])
        for r in from_ranges:
            r_line = r.get("start", {}).get("line", 0) + 1
            to_line = to_start.get("line", 0) + 1
            key = (to_path, to_line, to_name)
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"  {to_name} -> {to_path}:{to_line} "
                f"(called at line {r_line})"
            )
    if not lines:
        return "No outgoing calls found (this function calls nothing)."
    return f"Found {len(lines)} outgoing call(s):\n" + "\n".join(lines)


def _uri_to_path(uri: str) -> Path:
    """将 file:// URI 转换为 Path，正确处理 Windows 路径和百分号编码。"""
    if uri.startswith("file://"):
        parsed = urlparse(uri)
        path_str = unquote(parsed.path)
        # Windows: file:///E:/path -> /E:/path，去掉前导 /
        if len(path_str) >= 2 and path_str[0] == "/" and path_str[2] == ":":
            path_str = path_str[1:]
        return Path(path_str)
    return Path(unquote(uri))


def _symbol_kind_name(kind: int) -> str:
    """将 LSP SymbolKind 数值转换为可读名称。"""
    _KIND_NAMES = {
        1: "File",
        2: "Module",
        3: "Namespace",
        4: "Package",
        5: "Class",
        6: "Method",
        7: "Property",
        8: "Field",
        9: "Constructor",
        10: "Enum",
        11: "Interface",
        12: "Function",
        13: "Variable",
        14: "Constant",
        15: "String",
        16: "Number",
        17: "Boolean",
        18: "Array",
        19: "Object",
        20: "Key",
        21: "Null",
        22: "EnumMember",
        23: "Struct",
        24: "Event",
        25: "Operator",
        26: "TypeParameter",
    }
    return _KIND_NAMES.get(kind, "Symbol")
