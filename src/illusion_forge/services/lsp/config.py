"""
LSP 服务器配置管理
==================

内置各语言的默认 LSP 服务器配置，支持通过 settings.json 覆盖。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class LspServerConfig:
    """单个 LSP 服务器的配置。"""

    command: str
    args: list[str]
    extensions: list[str]
    env: dict[str, str] | None = None
    initialization_options: Any = None
    settings: Any = None
    startup_timeout: int = 30


# 内置默认配置
_LSP_DEFAULTS: dict[str, dict[str, Any]] = {
    "python": {
        "command": "pyright-langserver",
        "args": ["--stdio"],
        "extensions": [".py", ".pyi"],
    },
    "typescript": {
        "command": "typescript-language-server",
        "args": ["--stdio"],
        "extensions": [".ts", ".tsx", ".js", ".jsx"],
    },
    "go": {
        "command": "gopls",
        "args": [],
        "extensions": [".go"],
    },
    "rust": {
        "command": "rust-analyzer",
        "args": [],
        "extensions": [".rs"],
    },
    "cpp": {
        "command": "clangd",
        "args": [],
        "extensions": [".c", ".cpp", ".cc", ".h", ".hpp"],
    },
}


def load_lsp_config(settings_path: Path | None) -> dict[str, LspServerConfig]:
    """加载 LSP 配置：内置默认 + 用户覆盖。

    Args:
        settings_path: settings.json 路径，None 则只用默认配置

    Returns:
        language_id -> LspServerConfig 映射
    """
    # 从默认配置构建
    merged: dict[str, dict[str, Any]] = {}
    for lang, raw in _LSP_DEFAULTS.items():
        merged[lang] = dict(raw)

    # 读取用户配置并覆盖
    if settings_path and settings_path.exists():
        try:
            user_settings = json.loads(settings_path.read_text(encoding="utf-8"))
            user_lsp = user_settings.get("lsp_servers", {})
            for lang, raw in user_lsp.items():
                merged[lang] = dict(raw)
        except (json.JSONDecodeError, OSError):
            pass

    # 转换为 LspServerConfig
    configs: dict[str, LspServerConfig] = {}
    for lang, raw in merged.items():
        configs[lang] = LspServerConfig(
            command=raw["command"],
            args=raw.get("args", []),
            extensions=raw["extensions"],
            env=raw.get("env"),
            initialization_options=raw.get("initialization_options"),
            settings=raw.get("settings"),
            startup_timeout=raw.get("startup_timeout", 30),
        )

    return configs
