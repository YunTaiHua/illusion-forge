"""
LSP 符号提取器
==============

通过 LSP workspace/symbol 请求提取项目中所有语言的符号。
替代原有的 python_ast.py 和 enhanced_scan.py。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from illusion_forge.services.lsp.config import load_lsp_config
from illusion_forge.services.lsp.manager import LspManager
from illusion_forge.services.lsp.types import ModuleInfo, SymbolInfo, SymbolKind

logger = logging.getLogger(__name__)

# LSP SymbolKind 数值到 SymbolKind 枚举的映射
_KIND_MAP: dict[int, SymbolKind] = {v.value: v for v in SymbolKind}

# scanner 语言名到 LSP 语言 ID 的映射
_LANG_NAME_TO_LSP: dict[str, str] = {
    "python": "python",
    "typescript": "typescript",
    "javascript": "typescript",
    "react": "typescript",
    "go": "go",
    "rust": "rust",
    "c": "cpp",
    "c++": "cpp",
}


async def extract_symbols_via_lsp(
    root: Path,
    languages: dict[str, int],
    settings_path: Path | None = None,
) -> list[ModuleInfo]:
    """通过 LSP 提取所有语言的符号。

    Args:
        root: 项目根目录
        languages: 语言名 -> 文件数 映射（来自 scanner.py）
        settings_path: settings.json 路径

    Returns:
        ModuleInfo 列表
    """
    configs = load_lsp_config(settings_path)
    manager = LspManager(configs)

    all_modules: list[ModuleInfo] = []

    try:
        for lang_name in languages:
            lsp_lang_id = _LANG_NAME_TO_LSP.get(lang_name.lower())
            if lsp_lang_id is None:
                continue

            client = await manager.get_client_for_language(lsp_lang_id)
            if client is None:
                logger.info("LSP server not available for %s, skipping", lang_name)
                continue

            try:
                # 初始化（如果尚未初始化）
                if not client.is_initialized:
                    await client.initialize(root.as_uri())

                # workspace/symbol 获取所有符号
                raw_symbols = await client.request("workspace/symbol", {"query": ""}, timeout=60.0)
                if raw_symbols:
                    modules = _group_symbols_to_modules(raw_symbols, lsp_lang_id, root)
                    all_modules.extend(modules)
            except Exception:
                logger.warning("Failed to extract symbols for %s via LSP", lang_name, exc_info=True)
    finally:
        await manager.shutdown_all()

    return all_modules


def _group_symbols_to_modules(
    raw_symbols: list[dict[str, Any]],
    language: str,
    root: Path,
) -> list[ModuleInfo]:
    """将 LSP workspace/symbol 结果按文件分组为 ModuleInfo。"""
    by_file: dict[Path, list[SymbolInfo]] = defaultdict(list)

    for sym in raw_symbols:
        location = sym.get("location", {})
        uri = location.get("uri", "")
        if not uri:
            continue

        if uri.startswith("file://"):
            parsed = urlparse(uri)
            path_str = unquote(parsed.path)
            if len(path_str) >= 2 and path_str[0] == "/" and path_str[2] == ":":
                path_str = path_str[1:]
            file_path = Path(path_str)
        else:
            file_path = Path(unquote(uri))
        try:
            file_path = file_path.relative_to(root)
        except ValueError:
            pass

        range_ = location.get("range", {})
        start = range_.get("start", {})
        kind_val = sym.get("kind", 0)
        kind = _KIND_MAP.get(kind_val, SymbolKind.VARIABLE)

        symbol_info = SymbolInfo(
            name=sym.get("name", ""),
            kind=kind,
            path=file_path,
            line=start.get("line", 0) + 1,
            character=start.get("character", 0) + 1,
            container=sym.get("containerName", ""),
        )
        by_file[file_path].append(symbol_info)

    modules: list[ModuleInfo] = []
    for file_path, symbols in by_file.items():
        modules.append(
            ModuleInfo(
                path=file_path,
                language=language,
                docstring=None,
                symbols=symbols,
                imports=[],
            )
        )

    return modules


def extract_symbols_sync(
    root: Path,
    languages: dict[str, int],
    settings_path: Path | None = None,
) -> list[ModuleInfo]:
    """同步版本的符号提取（供 orchestrator 使用）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                extract_symbols_via_lsp(root, languages, settings_path),
            )
            return future.result()
    else:
        return asyncio.run(extract_symbols_via_lsp(root, languages, settings_path))
