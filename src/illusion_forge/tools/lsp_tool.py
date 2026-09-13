"""
LSP 代码智能工具
================

支持所有已配置语言的代码智能操作。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from illusion_forge.services.lsp.config import load_lsp_config
from illusion_forge.services.lsp.manager import LspManager
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult
from illusion_forge.tools.lsp_formatters import (
    format_document_symbol,
    format_find_references,
    format_go_to_definition,
    format_hover,
    format_incoming_calls,
    format_outgoing_calls,
    format_prepare_call_hierarchy,
    format_workspace_symbol,
    resolve_path,
)
from illusion_forge.tools.lsp_schemas import LspToolInput

logger = logging.getLogger(__name__)

# 全局 LSP 管理器实例（延迟初始化，线程安全）
# LspManager 持有子进程，必须保证单例，不能用 ContextVar
_manager: LspManager | None = None
_manager_lock = threading.Lock()
# 跟踪已打开的文件 URI -> language_id（会话级隔离，轻量数据用 ContextVar）
_opened_files_var: ContextVar[dict[str, str]] = ContextVar("lsp_tool.opened_files")


def _get_opened_files() -> dict[str, str]:
    """获取当前会话的已打开文件映射（懒初始化）"""
    try:
        return _opened_files_var.get()
    except LookupError:
        d: dict[str, str] = {}
        _opened_files_var.set(d)
        return d


def _get_manager() -> LspManager:
    """获取或创建全局 LspManager 实例（线程安全单例）。"""
    global _manager
    if _manager is not None:
        return _manager
    with _manager_lock:
        if _manager is not None:
            return _manager
        from illusion_forge.config.paths import get_config_file_path

        settings_path = get_config_file_path()
        configs = load_lsp_config(settings_path)
        _manager = LspManager(configs)
        return _manager


class LspTool(BaseTool[LspToolInput]):
    """LSP 代码智能工具。"""

    name = "lsp"
    description = """Interact with Language Server Protocol (LSP) servers to get code intelligence features.

Supported operations:
- goToDefinition: Find where a symbol is defined
- findReferences: Find all references to a symbol
- hover: Get hover information (documentation, type info) for a symbol
- documentSymbol: Get all symbols (functions, classes, variables) in a document
- workspaceSymbol: Search for symbols across the entire workspace (requires 'query' parameter)
- goToImplementation: Find implementations of an interface or abstract method
- prepareCallHierarchy: Get call hierarchy item at a position (functions/methods)
- incomingCalls: Find all functions/methods that call the function at a position
- outgoingCalls: Find all functions/methods called by the function at a position

All operations require:
- filePath: The file to operate on
- line: The line number (1-based, as shown in editors)
- character: The character offset (1-based, as shown in editors)

Note: LSP servers must be configured for the file type. If no server is available, an error will be returned."""

    input_model = LspToolInput

    @staticmethod
    def _find_workspace_root(file_path: Path, cwd: Path) -> Path:
        """查找文件的工作区根目录。"""
        current = file_path.parent
        for marker in (".git", "pyproject.toml", "package.json", "go.mod", "Cargo.toml"):
            check = current
            while check != check.parent:
                if (check / marker).exists():
                    return check
                check = check.parent
        return cwd

    def is_read_only(self, arguments: LspToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: LspToolInput, context: ToolExecutionContext) -> ToolResult:
        manager = _get_manager()
        root = context.cwd.resolve()
        op = arguments.operation

        # activate 操作：激活所有可用的 LSP 服务器
        if op == "activate":
            return await self._activate_servers(manager, root)

        # workspaceSymbol 不需要 filePath
        if op == "workspaceSymbol":
            return await self._workspace_symbol(manager, root, arguments)

        if not arguments.filePath:
            return ToolResult(output="filePath is required for this operation.", is_error=True)

        file_path = resolve_path(root, arguments.filePath)
        if not await asyncio.to_thread(file_path.exists):
            return ToolResult(output=f"File not found: {file_path}", is_error=True)

        lang_id = manager.get_language_id(file_path)
        if lang_id is None:
            return ToolResult(
                output=(
                    f"Unsupported file type: {file_path.suffix}. "
                    f"Supported: {', '.join(sorted(manager.supported_extensions))}"
                ),
                is_error=True,
            )

        client = await manager.get_client(file_path)
        if client is None:
            if not manager._activated:
                return ToolResult(
                    output=(
                        f"LSP server for '{lang_id}' is not activated. "
                        f"Use operation='activate' to activate all LSP servers."
                    ),
                    is_error=True,
                )
            config = manager._configs.get(lang_id)
            install_hint = f"{config.command}" if config else "the LSP server"
            return ToolResult(
                output=(
                    f"LSP server for '{lang_id}' failed to start. "
                    f"{install_hint} may not be installed. "
                    f"Use operation='activate' to retry."
                ),
                is_error=True,
            )

        # 初始化 LSP 服务器
        if not client.is_initialized:
            workspace_root = self._find_workspace_root(file_path, root)
            await manager.initialize_client(lang_id, workspace_root.as_uri(), root_path=str(workspace_root))

        # LSP 位置参数（0-based）
        position = {"line": arguments.line - 1, "character": arguments.character - 1}
        text_doc = {"uri": file_path.as_uri()}

        # 确保文件已打开（参考项目模式：先 openFile 再发请求）
        opened_files = _get_opened_files()
        if opened_files.get(text_doc["uri"]) != lang_id:
            await self._open_file(client, file_path, lang_id, text_doc["uri"])

        try:
            if op == "goToDefinition":
                return await self._go_to_definition(client, root, text_doc, position)
            elif op == "findReferences":
                return await self._find_references(client, root, text_doc, position)
            elif op == "hover":
                return await self._hover(client, root, text_doc, position)
            elif op == "documentSymbol":
                return await self._document_symbol(client, root, text_doc)
            elif op == "goToImplementation":
                return await self._go_to_implementation(client, root, text_doc, position)
            elif op == "prepareCallHierarchy":
                return await self._prepare_call_hierarchy(client, root, text_doc, position)
            elif op == "incomingCalls":
                return await self._incoming_calls(client, root, text_doc, position)
            elif op == "outgoingCalls":
                return await self._outgoing_calls(client, root, text_doc, position)
            else:
                return ToolResult(output=f"Unknown operation: {op}", is_error=True)
        except TimeoutError:
            return ToolResult(output=f"LSP operation '{op}' timed out.", is_error=True)
        except RuntimeError as e:
            msg = str(e)
            if "Unhandled method" in msg:
                return ToolResult(
                    output=f"The LSP server for {lang_id} does not support the '{op}' operation.",
                    is_error=True,
                )
            return ToolResult(output=f"LSP error: {msg}", is_error=True)

    @staticmethod
    async def _open_file(client: Any, file_path: Path, lang_id: str, file_uri: str) -> None:
        """打开文件并等待服务器分析完成。"""
        try:
            content = await asyncio.to_thread(file_path.read_text, encoding="utf-8", errors="replace")

            # 等待诊断通知
            diag_event = asyncio.Event()
            def _on_diag(params: dict[str, Any]) -> None:
                if params.get("uri") == file_uri:
                    diag_event.set()
            client.on_notification("textDocument/publishDiagnostics", _on_diag)

            await client.notify("textDocument/didOpen", {
                "textDocument": {
                    "uri": file_uri,
                    "languageId": lang_id,
                    "version": 1,
                    "text": content,
                },
            })
            _get_opened_files()[file_uri] = lang_id

            # 等待服务器分析完成（最长 10 秒）
            try:
                await asyncio.wait_for(diag_event.wait(), timeout=10)
            except TimeoutError:
                pass
        except (OSError, RuntimeError):
            logger.debug("[lsp_tool] Failed to open file %s", file_path, exc_info=True)

    async def _activate_servers(self, manager: Any, root: Path) -> ToolResult:
        """激活所有可用的 LSP 服务器。"""
        results = await manager.activate_all()
        if not results:
            return ToolResult(
                output="No LSP servers configured.",
                metadata={"operation": "activate", "result_count": 0},
            )

        lines = [f"{lang}: {status}" for lang, status in results.items()]
        return ToolResult(
            output="LSP server activation status:\n" + "\n".join(f"  {l}" for l in lines),
            metadata={"operation": "activate", "result_count": len(results)},
        )

    async def _go_to_definition(self, client: Any, root: Path, text_doc: dict[str, Any], position: dict[str, Any]) -> ToolResult:
        result = await client.request(
            "textDocument/definition",
            textDocument=text_doc, position=position,
        )
        results = result if isinstance(result, list) else [result] if result else []
        return ToolResult(
            output=format_go_to_definition(results, root),
            metadata={"operation": "goToDefinition", "result_count": len(results), "file_count": len({loc.get("uri", "") for loc in results if loc.get("uri")})},
        )

    async def _find_references(self, client: Any, root: Path, text_doc: dict[str, Any], position: dict[str, Any]) -> ToolResult:
        result = await client.request(
            "textDocument/references",
            textDocument=text_doc, position=position, context={"includeDeclaration": True},
        )
        return ToolResult(
            output=format_find_references(result or [], root),
            metadata={"operation": "findReferences", "result_count": len(result or []), "file_count": len({loc.get("uri", "") for loc in (result or []) if loc.get("uri")})},
        )

    async def _hover(self, client: Any, root: Path, text_doc: dict[str, Any], position: dict[str, Any]) -> ToolResult:
        result = await client.request(
            "textDocument/hover",
            textDocument=text_doc, position=position,
        )
        return ToolResult(
            output=format_hover(result, root),
            metadata={"operation": "hover", "result_count": 1 if result else 0, "file_count": 1 if result else 0},
        )

    async def _document_symbol(self, client: Any, root: Path, text_doc: dict[str, Any]) -> ToolResult:
        result = await client.request(
            "textDocument/documentSymbol",
            textDocument=text_doc,
        )
        return ToolResult(
            output=format_document_symbol(result or [], root),
            metadata={"operation": "documentSymbol", "result_count": len(result or []), "file_count": 1},
        )

    async def _workspace_symbol(self, manager: Any, root: Path, arguments: LspToolInput) -> ToolResult:
        query = arguments.query or arguments.filePath or ""
        if not query:
            return ToolResult(
                output="workspaceSymbol requires a query. Use the 'query' parameter.",
                is_error=True,
                metadata={"operation": "workspaceSymbol", "result_count": 0, "file_count": 0},
            )

        if not manager._activated:
            return ToolResult(
                output=(
                    "LSP server is not activated. "
                    "Use operation='activate' to activate all LSP servers."
                ),
                is_error=True,
                metadata={"operation": "workspaceSymbol", "result_count": 0, "file_count": 0},
            )

        all_results: list[dict[str, Any]] = []
        query_lower = query.lower()

        # 收集项目中的所有源文件
        source_files: list[tuple[Path, str]] = []
        skip_names = {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build", "target", "vendor"}
        # rglob 可能在大仓库上耗时较长，委托给线程池避免阻塞事件循环
        all_files = await asyncio.to_thread(lambda: list(root.rglob("*")))
        for f in all_files:
            if not f.is_file():
                continue
            if any(p in skip_names for p in f.relative_to(root).parts):
                continue
            lang_id = manager.get_language_id(f)
            if lang_id:
                source_files.append((f, lang_id))

        # 按语言分组
        by_lang: dict[str, list[Path]] = {}
        for f, lid in source_files:
            by_lang.setdefault(lid, []).append(f)

        for lang_id, files in by_lang.items():
            client = await manager.get_client_for_language(lang_id)
            if client is None:
                continue
            if not client.is_alive:
                manager._clients.pop(lang_id, None)
                client = await manager.get_client_for_language(lang_id)
                if client is None:
                    continue
            if not client.is_initialized:
                await manager.initialize_client(lang_id, root.as_uri(), root_path=str(root))
            if not client.is_alive:
                continue

            for file_path in files:
                if len(all_results) >= 10:
                    break
                try:
                    content = await asyncio.to_thread(
                        file_path.read_text, encoding="utf-8", errors="replace"
                    )
                    file_uri = file_path.as_uri()

                    if file_uri not in _get_opened_files():
                        await client.notify("textDocument/didOpen", textDocument={
                            "uri": file_uri, "languageId": lang_id, "version": 1, "text": content,
                        })
                        _get_opened_files()[file_uri] = lang_id

                    symbols = await client.request(
                        "textDocument/documentSymbol",
                        textDocument={"uri": file_uri},
                        timeout=10,
                    )
                    if symbols:
                        for sym in symbols:
                            name = sym.get("name", "")
                            if not name or name.startswith("<"):
                                continue
                            if query_lower in name.lower():
                                range_ = sym.get("range", {})
                                all_results.append({
                                    "name": name,
                                    "kind": sym.get("kind", 0),
                                    "location": {"uri": file_uri, "range": range_},
                                    "containerName": sym.get("containerName", ""),
                                })
                                if len(all_results) >= 10:
                                    break
                except (OSError, RuntimeError, TimeoutError):
                    logger.debug("[lsp_tool] Failed to fetch symbols from %s", file_path, exc_info=True)
                    continue
            if len(all_results) >= 10:
                break

        if not all_results:
            return ToolResult(
            output=f"No symbols matching '{query}' found in workspace.",
            metadata={"operation": "workspaceSymbol", "result_count": 0, "file_count": 0},
        )
        return ToolResult(
            output=format_workspace_symbol(all_results, root),
            metadata={"operation": "workspaceSymbol", "result_count": len(all_results), "file_count": len({sym.get("location", {}).get("uri", "") for sym in all_results if sym.get("location", {}).get("uri")})},
        )

    async def _go_to_implementation(self, client: Any, root: Path, text_doc: dict[str, Any], position: dict[str, Any]) -> ToolResult:
        result = await client.request(
            "textDocument/implementation",
            textDocument=text_doc, position=position,
        )
        results = result if isinstance(result, list) else [result] if result else []
        return ToolResult(
            output=format_go_to_definition(results, root),
            metadata={"operation": "goToImplementation", "result_count": len(results), "file_count": len({loc.get("uri", "") for loc in results if loc.get("uri")})},
        )

    async def _prepare_call_hierarchy(self, client: Any, root: Path, text_doc: dict[str, Any], position: dict[str, Any]) -> ToolResult:
        result = await client.request(
            "textDocument/prepareCallHierarchy",
            textDocument=text_doc, position=position,
        )
        return ToolResult(
            output=format_prepare_call_hierarchy(result or [], root),
            metadata={"operation": "prepareCallHierarchy", "result_count": len(result or []), "file_count": len({item.get("uri", "") for item in (result or []) if item.get("uri")})},
        )

    async def _incoming_calls(self, client: Any, root: Path, text_doc: dict[str, Any], position: dict[str, Any]) -> ToolResult:
        items = await client.request(
            "textDocument/prepareCallHierarchy",
            textDocument=text_doc, position=position,
        )
        if not items:
            return ToolResult(output="No incoming calls found (nothing calls this function).", metadata={"operation": "incomingCalls", "result_count": 0, "file_count": 0})
        item = items[0] if isinstance(items, list) else items
        result = await client.request("callHierarchy/incomingCalls", item=item)
        return ToolResult(
            output=format_incoming_calls(result or [], root),
            metadata={"operation": "incomingCalls", "result_count": len(result or []), "file_count": len({call.get("from", {}).get("uri", "") for call in (result or []) if call.get("from", {}).get("uri")})},
        )

    async def _outgoing_calls(self, client: Any, root: Path, text_doc: dict[str, Any], position: dict[str, Any]) -> ToolResult:
        items = await client.request(
            "textDocument/prepareCallHierarchy",
            textDocument=text_doc, position=position,
        )
        if not items:
            return ToolResult(output="No outgoing calls found (this function calls nothing).", metadata={"operation": "outgoingCalls", "result_count": 0, "file_count": 0})
        item = items[0] if isinstance(items, list) else items
        result = await client.request("callHierarchy/outgoingCalls", item=item)
        return ToolResult(
            output=format_outgoing_calls(result or [], root),
            metadata={"operation": "outgoingCalls", "result_count": len(result or []), "file_count": len({call.get("to", {}).get("uri", "") for call in (result or []) if call.get("to", {}).get("uri")})},
        )
