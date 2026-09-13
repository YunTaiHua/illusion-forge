"""
IllusionForge CLI 包
====================

本包提供 IllusionForge 命令行入口，使用 typer 构建。Web UI 是唯一的交互
界面：`illusion-forge`（无子命令）与 `illusion-forge forge` 都会启动它；`-p/--print`
进入无头模式，供 cron 与脚本调用。

主要功能：
    - 启动 Web UI（默认）
    - 无头打印模式（-p）
    - MCP 服务器管理
    - 插件管理
    - 认证管理
    - 资源添加（model）
    - Cron 任务调度管理
    - 渠道管理
    - 自更新
    - 工作目录管理（set）

子命令说明：
    - mcp: MCP 服务器管理（list、add、remove）
    - plugin: 插件管理（list、install、uninstall）
    - auth: 认证管理（login、status、logout、switch）
    - add: 向已有环境添加资源（model）
    - cron: Cron 调度管理（start、stop、status、list、toggle、history、logs）
    - channel: 渠道管理（login、serve、status、enable、disable、logout）
    - forge: 启动 Web UI（可指定端口/监听地址；不用 `web` 以免与 illusion-agent 的同名子命令混淆）
    - update: 自更新
    - set: 设置工作目录

使用示例：
    >>> illusion-forge              # 启动 Web UI
    >>> illusion-forge forge --port 3200  # 指定端口启动 Web UI
    >>> illusion-forge -p "你的提示词"     # 无头打印模式
    >>> illusion-forge auth login         # 认证登录（新建 env）
    >>> illusion-forge set "E:\\Projects" # 设置工作目录
"""
from __future__ import annotations

import sys
from typing import Any, cast

import typer

from illusion_forge import __version__


class _ReconfigurableStream:
    """支持 reconfigure 方法的流类型（用于类型安全地调用 stdout/stderr.reconfigure）。"""

    def reconfigure(self, **kwargs: Any) -> None: ...


# 确保 Windows 上 stdout/stderr 使用 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    cast(_ReconfigurableStream, sys.stdout).reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    cast(_ReconfigurableStream, sys.stderr).reconfigure(encoding="utf-8", errors="replace")


def _version_callback(value: bool) -> None:
    """版本回调函数"""
    if value:
        print(f"illusion-forge {__version__}")
        raise typer.Exit()


# 创建主应用程序
app = typer.Typer(
    name="illusion-forge",
    help=(
        "Illusion Forge - AI 驱动的 CAD 工作台与编程助手\n"
        "默认启动 Web UI，使用 -p/--print 进入无头模式"
    ),
    add_completion=False,
    rich_markup_mode="rich",
    invoke_without_command=True,
)

# 创建子命令应用
mcp_app = typer.Typer(name="mcp", help="MCP 服务器管理 / Manage MCP servers")
plugin_app = typer.Typer(name="plugin", help="插件管理 / Manage plugins")
auth_app = typer.Typer(name="auth", help="认证管理 / Manage authentication")
cron_app = typer.Typer(name="cron", help="定时任务管理 / Manage cron scheduler and jobs")
forge_app = typer.Typer(name="forge", help="启动 Illusion Forge Web 界面 / Launch the Illusion Forge Web UI")
add_app = typer.Typer(name="add", help="添加资源 / Add resources (e.g. add model to existing env)")
channel_app = typer.Typer(name="channel", help="渠道管理 / Manage messaging channels")

# 注册子命令到主应用
app.add_typer(mcp_app)
app.add_typer(plugin_app)
app.add_typer(auth_app)
app.add_typer(cron_app)
app.add_typer(forge_app)
app.add_typer(add_app)
app.add_typer(channel_app)

# 导入各子命令模块以触发命令注册（顺序重要：先 shared/workspace，再子命令，最后 main）
# 使用 importlib.import_module 进行副作用导入，避免未使用导入告警
import importlib

for _module_name in (
    "shared",
    "workspace",
    "mcp",
    "plugin",
    "cron",
    "auth",
    "forge",
    "update",
    "channel",
    "main",
):
    importlib.import_module(f"illusion_forge.cli.{_module_name}")

__all__ = ["app"]
