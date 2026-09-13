"""
LSP 多语言管理器
================

管理多个 LSP 服务器实例，按文件扩展名路由请求。
按需启动服务器，管理文件同步生命周期。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from illusion_forge.services.lsp.client import LspClient
from illusion_forge.services.lsp.config import LspServerConfig

logger = logging.getLogger(__name__)


class LspManager:
    """管理多个 LSP 服务器实例，按文件扩展名路由。"""

    # 启动失败后的冷却时间（秒）
    _FAIL_COOLDOWN = 30.0

    def __init__(self, configs: dict[str, LspServerConfig]) -> None:
        self._configs = configs
        self._clients: dict[str, LspClient] = {}
        self._starting: dict[str, bool] = {}
        self._last_fail: dict[str, float] = {}  # lang_id -> last failure timestamp
        self._activated: bool = False  # 是否已手动激活

        # 构建扩展名 -> 语言 ID 映射
        self._ext_map: dict[str, str] = {}
        for lang_id, config in configs.items():
            for ext in config.extensions:
                self._ext_map[ext] = lang_id

    @property
    def supported_extensions(self) -> set[str]:
        """返回所有支持的文件扩展名。"""
        return set(self._ext_map.keys())

    def get_language_id(self, file_path: Path) -> str | None:
        """根据文件扩展名获取语言 ID。"""
        return self._ext_map.get(file_path.suffix)

    async def get_client(self, file_path: Path) -> LspClient | None:
        """获取文件对应语言的 LSP 客户端，按需启动。

        Args:
            file_path: 文件路径

        Returns:
            LspClient 实例，若该语言无配置则返回 None
        """
        lang_id = self.get_language_id(file_path)
        if lang_id is None:
            return None
        return await self._get_or_start_client(lang_id)

    async def get_client_for_language(self, lang_id: str) -> LspClient | None:
        """直接按语言 ID 获取客户端。"""
        if lang_id not in self._configs:
            return None
        return await self._get_or_start_client(lang_id)

    async def request(self, file_path: Path, method: str, params: Any, timeout: float = 30.0) -> Any:
        """向文件对应语言的 LSP 服务器发送请求。"""
        client = await self.get_client(file_path)
        if client is None:
            return None
        return await client.request(method, params, timeout=timeout)

    async def notify(self, file_path: Path, method: str, params: Any) -> None:
        """向文件对应语言的 LSP 服务器发送通知。"""
        client = await self.get_client(file_path)
        if client is not None:
            await client.notify(method, params)

    async def shutdown_all(self) -> None:
        """并行关闭所有 LSP 服务器。

        每个 ``client.stop()`` 内部会 ``await asyncio.to_thread(proc.wait, timeout=5)``，
        串行执行时 N 个客户端要等 5N 秒；用 ``asyncio.gather`` 并行后总时长收敛到 ~5 秒。
        """
        if not self._clients:
            self._starting.clear()
            return
        results = await asyncio.gather(
            *(client.stop() for client in self._clients.values()),
            return_exceptions=True,
        )
        for client, result in zip(self._clients.values(), results):
            if isinstance(result, Exception):
                logger.exception("Error stopping LSP client: %s", client, exc_info=result)
        self._clients.clear()
        self._starting.clear()

    async def initialize_client(self, lang_id: str, root_uri: str, root_path: str | None = None) -> None:
        """初始化指定语言的 LSP 客户端（如果尚未初始化）。"""
        client = self._clients.get(lang_id)
        if client is None or client.is_initialized:
            return

        import os
        await client.initialize(
            root_uri=root_uri,
            root_path=root_path,
            process_id=os.getpid(),
            capabilities={
                "window": {
                    "workDoneProgress": True,
                },
                "workspace": {
                    "configuration": False,
                    "workspaceFolders": False,
                },
                "textDocument": {
                    "synchronization": {
                        "dynamicRegistration": False,
                        "willSave": False,
                        "willSaveWaitUntil": False,
                        "didSave": True,
                    },
                    "publishDiagnostics": {
                        "relatedInformation": True,
                        "tagSupport": {"valueSet": [1, 2]},
                        "versionSupport": False,
                        "codeDescriptionSupport": True,
                        "dataSupport": False,
                    },
                    "hover": {
                        "dynamicRegistration": False,
                        "contentFormat": ["markdown", "plaintext"],
                    },
                    "definition": {
                        "dynamicRegistration": False,
                        "linkSupport": True,
                    },
                    "references": {
                        "dynamicRegistration": False,
                    },
                    "documentSymbol": {
                        "dynamicRegistration": False,
                        "hierarchicalDocumentSymbolSupport": True,
                    },
                    "implementation": {
                        "dynamicRegistration": False,
                    },
                    "callHierarchy": {
                        "dynamicRegistration": False,
                    },
                },
                "general": {
                    "positionEncodings": ["utf-16"],
                },
            },
        )

    @staticmethod
    def _handle_workspace_config(params: Any) -> list[Any]:
        """处理 workspace/configuration 请求。"""
        items = params.get("items", []) if isinstance(params, dict) else []
        return [{}] * len(items)

    @staticmethod
    def _handle_work_done_progress(params: Any) -> None:
        """处理 window/workDoneProgress/create 请求。"""
        return

    @staticmethod
    def _handle_workspace_folders(params: Any) -> list[Any]:
        """处理 workspace/workspaceFolders 请求。"""
        return []

    async def _get_or_start_client(self, lang_id: str) -> LspClient | None:
        """获取或启动指定语言的 LSP 客户端。

        仅当已手动激活（activate_all）后才允许自动启动服务器。
        """
        # 检查已有客户端是否仍可用
        if lang_id in self._clients:
            client = self._clients[lang_id]
            if client._connected and client.is_alive:
                return client
            # 连接已断开或进程已退出，移除并重新启动
            logger.info("LSP client for %s unavailable (connected=%s, alive=%s), restarting",
                        lang_id, client._connected, client.is_alive)
            self._clients.pop(lang_id, None)

        # 未手动激活时不允许自动启动
        if not self._activated:
            return None

        if lang_id in self._starting:
            return None  # 正在启动中

        # 冷却检查：启动失败后短时间内不再重试
        last_fail = self._last_fail.get(lang_id, 0)
        if time.monotonic() - last_fail < self._FAIL_COOLDOWN:
            return None

        config = self._configs.get(lang_id)
        if config is None:
            return None

        # 预检命令是否存在（Windows shell=True 不会抛 FileNotFoundError）
        import shutil
        if shutil.which(config.command) is None:
            logger.warning("LSP server not found for %s: %s", lang_id, config.command)
            self._last_fail[lang_id] = time.monotonic()
            return None

        self._starting[lang_id] = True
        try:
            client = LspClient()
            # 在启动前注册请求处理器，防止服务器发送请求时无响应
            client.on_request("workspace/configuration", self._handle_workspace_config)
            client.on_request("window/workDoneProgress/create", self._handle_work_done_progress)
            client.on_request("workspace/workspaceFolders", self._handle_workspace_folders)
            await client.start(config.command, config.args)
            self._clients[lang_id] = client
            logger.info("Started LSP server for %s: %s", lang_id, config.command)
            return client
        except FileNotFoundError:
            logger.warning("LSP server not found for %s: %s", lang_id, config.command)
            self._last_fail[lang_id] = time.monotonic()
            return None
        except Exception:
            logger.exception("Failed to start LSP server for %s", lang_id)
            self._last_fail[lang_id] = time.monotonic()
            return None
        finally:
            self._starting.pop(lang_id, None)

    async def activate_all(self) -> dict[str, str]:
        """手动激活所有 LSP 服务器。

        返回每个语言的激活状态：activated / failed / starting。
        """
        self._activated = True
        results: dict[str, str] = {}
        for lang_id, config in self._configs.items():
            client = await self._get_or_start_client(lang_id)
            if client is None:
                if lang_id in self._last_fail:
                    results[lang_id] = f"failed to start, {config.command} may not be installed"
                else:
                    results[lang_id] = "not available (starting or in cooldown)"
                continue

            if not client.is_initialized:
                try:
                    # 使用临时 root_uri，实际初始化为 workspace root 时再重新初始化
                    await self.initialize_client(lang_id, "file:///", root_path="/")
                except (RuntimeError, TimeoutError, OSError) as e:
                    results[lang_id] = f"initialization failed - {e}"
                    continue

            if client.is_initialized and client.is_alive:
                results[lang_id] = f"activated ({config.command})"
            else:
                results[lang_id] = f"starting ({config.command})"
        return results
