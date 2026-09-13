"""
MCP 服务器配置加载模块
=====================

本模块提供从设置、插件和项目目录加载 MCP 服务器配置的功能。

主要功能：
    - 从全局设置中加载 MCP 服务器配置
    - 从已加载的插件中合并 MCP 服务器配置
    - 从项目级配置目录加载 MCP 服务器配置
    - 插件配置优先级高于全局设置（同名配置）

函数说明：
    - load_mcp_server_configs: 加载并合并 MCP 服务器配置
    - load_project_mcp_configs: 从项目目录加载 MCP 配置

使用示例：
    >>> from illusion_forge.mcp.config import load_mcp_server_configs
    >>> configs = load_mcp_server_configs(settings, plugins, cwd="/path/to/project")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from illusion_forge.config.paths import get_project_mcp_dir
from illusion_forge.mcp.types import McpServerConfig, _normalize_server_config_type
from illusion_forge.plugins.types import LoadedPlugin

logger = logging.getLogger(__name__)


def load_project_mcp_configs(cwd: str | Path) -> dict[str, object]:
    """
    从项目目录加载 MCP 服务器配置

    扫描 <project>/.illusion/mcp/ 目录下的所有 JSON 文件，
    每个文件可以包含一个或多个 MCP 服务器配置。

    文件格式支持：
    1. 单个服务器配置（文件名作为服务器名）：
       {"type": "stdio", "command": "python", "args": ["server.py"]}
       省略 type 字段时默认按 stdio 处理：
       {"command": "python", "args": ["server.py"]}

    2. 多个服务器配置（使用 mcpServers 键）：
       {"mcpServers": {"server1": {...}, "server2": {...}}}

    Args:
        cwd: 当前工作目录

    Returns:
        dict[str, object]: 服务器名称到配置的映射字典
    """
    _server_adapter: TypeAdapter[McpServerConfig] = TypeAdapter(McpServerConfig)
    servers: dict[str, object] = {}
    mcp_dir = get_project_mcp_dir(cwd)

    if not mcp_dir.exists():
        return servers

    for json_file in sorted(mcp_dir.glob("*.json")):
        try:
            raw = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read MCP config %s: %s", json_file, exc)
            continue

        servers.update(_parse_mcp_config_dict(raw, _server_adapter, source=json_file))

    return servers


def _looks_like_server_config(value: object) -> bool:
    """判断一个 dict 是否像是单个 MCP 服务器配置（含 type/command/url 等特征字段）。"""
    if not isinstance(value, dict):
        return False
    return any(k in value for k in ("type", "command", "url", "args"))


def _parse_mcp_config_dict(
    raw: dict[str, Any],
    server_adapter: TypeAdapter[McpServerConfig],
    *,
    source: object | None = None,
) -> dict[str, object]:
    """解析一个 MCP 配置 dict 为 {server_name: config} 映射。

    支持三种格式：
    1. {"mcpServers": {...}} / {"mcp_servers": {...}}（标准多服务器格式）
    2. {"server-name": {...}, ...}（无包装的多服务器格式，每个 value 必须像 server config）
    3. {"type": "stdio", ...}（单服务器配置，使用 "_inline" 或文件名作为名称；
       省略 type 字段时默认按 stdio 处理）
    """
    from illusion_forge.mcp.types import McpJsonConfig

    # 兼容 mcp_servers（snake_case）键
    if "mcp_servers" in raw and "mcpServers" not in raw:
        raw["mcpServers"] = raw.pop("mcp_servers")

    servers: dict[str, object] = {}

    # 格式 1：mcpServers 键
    if "mcpServers" in raw:
        try:
            parsed = McpJsonConfig.model_validate(raw)
            for name, config in parsed.mcpServers.items():
                if getattr(config, "enabled", True):
                    servers[name] = config
        except ValidationError as exc:
            logger.warning("Failed to parse MCP config %s: %s", source or "input", exc)
        return servers

    # 格式 2：{"server-name": {...}} 无包装多服务器格式
    # 判定条件：所有 value 都是 dict 且像 server config（且顶层自身不像单个 server config）
    if isinstance(raw, dict) and raw and not _looks_like_server_config(raw):
        all_values_like_config = all(
            isinstance(v, dict) and _looks_like_server_config(v) for v in raw.values()
        )
        if all_values_like_config:
            for name, server_cfg in raw.items():
                try:
                    config = server_adapter.validate_python(
                        _normalize_server_config_type(server_cfg)
                    )
                    if getattr(config, "enabled", True):
                        servers[name] = config
                except ValidationError as exc:
                    logger.warning(
                        "Failed to parse MCP server '%s' in %s: %s",
                        name,
                        source or "input",
                        exc,
                    )
            return servers

    # 格式 3：单服务器配置
    try:
        config = server_adapter.validate_python(_normalize_server_config_type(raw))
        if getattr(config, "enabled", True):
            name = Path(str(source)).stem if source else "_inline"
            servers[name] = config
    except ValidationError as exc:
        logger.warning("Failed to parse MCP config %s: %s", source or "input", exc)

    return servers


def load_mcp_server_configs(settings: Any, plugins: list[LoadedPlugin], cwd: str | Path | None = None) -> dict[str, object]:
    """
    加载 MCP 服务器配置

    从全局设置、项目目录和已加载的插件中合并 MCP 服务器配置。
    优先级（从高到低）：插件 > 项目级 > 全局设置

    Args:
        settings: 全局设置对象，包含 mcp_servers 属性
        plugins: 已加载的插件列表，每个插件包含 mcp_servers 属性
        cwd: 当前工作目录，用于加载项目级配置

    Returns:
        dict[str, object]: 服务器名称到配置的映射字典
                         键的格式为 "插件名:服务器名"（来自插件）或仅"服务器名"（来自其他来源）

    使用示例：
        >>> configs = load_mcp_server_configs(settings, plugins, cwd="/path/to/project")
        >>> for name, config in configs.items():
        ...     print(f"{name}: {config}")
    """
    # 加载项目级权限配置
    from illusion_forge.permissions.loader import load_project_permissions
    project_permissions = load_project_permissions(cwd) if cwd else None

    # 检查是否禁用所有 MCP 服务器
    if project_permissions and "*" in project_permissions.denied_mcp_servers:
        return {}

    # 从全局设置中获取 MCP 服务器配置（跳过已禁用的服务器）
    servers = {name: cfg for name, cfg in settings.mcp_servers.items()
               if getattr(cfg, "enabled", True)}

    # 从项目目录加载 MCP 配置（覆盖全局设置）
    if cwd is not None:
        project_configs = load_project_mcp_configs(cwd)
        servers.update(project_configs)

    # 遍历所有已加载的插件
    for plugin in plugins:
        # 跳过未启用的插件
        if not plugin.enabled:
            continue
        # 将插件的 MCP 服务器配置合并到结果中（跳过已禁用的服务器）
        for name, config in plugin.mcp_servers.items():
            if not getattr(config, "enabled", True):
                continue
            # 使用 "插件名:服务器名" 格式作为键，避免与全局设置冲突
            servers.setdefault(f"{plugin.manifest.name}:{name}", config)

    # 过滤掉被禁用的 MCP 服务器
    if project_permissions:
        servers = {
            name: cfg for name, cfg in servers.items()
            if name not in project_permissions.denied_mcp_servers
        }

    return servers


def load_mcp_config_from_string(cfg: str) -> dict[str, object]:
    """从 JSON 字符串或文件路径加载 MCP 服务器配置。

    支持两种输入：
    1. 文件路径（Path 存在时）：读取 JSON 文件
    2. JSON 字符串：直接解析

    支持三种格式：
    1. {"mcpServers": {...}} / {"mcp_servers": {...}}（标准多服务器）
    2. {"server-name": {...}, ...}（无包装多服务器）
    3. {...}（单服务器配置，返回 {"_inline": config}）

    Args:
        cfg: 文件路径或 JSON 字符串

    Returns:
        dict[str, object]: 服务器名称到配置的映射
    """

    _server_adapter: TypeAdapter[McpServerConfig] = TypeAdapter(McpServerConfig)

    # 判断是文件路径还是 JSON 字符串
    cfg_path = Path(cfg)
    source = cfg_path if cfg_path.exists() else None
    if source is not None:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    else:
        raw = json.loads(cfg)

    if not isinstance(raw, dict):
        return {}

    return _parse_mcp_config_dict(raw, _server_adapter, source=source or "_inline")
