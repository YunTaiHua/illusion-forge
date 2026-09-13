"""QQ 渠道模块
================

提供 IllusionForge 的 QQ（QQ 开放平台 Bot API v2）消息渠道实现。

子模块：
    - api: QQ Bot REST API 客户端（token/收发/上传）
    - ws_client: WebSocket 网关客户端（心跳/重连/事件分发）
    - adapter: QQ 渠道适配器（连接/准入/消息标准化）
    - session_map: QQ 会话存储
    - commands: QQ 侧斜杠命令

本包内部延迟导入 aiohttp，确保未安装依赖时主程序不崩溃。
"""
from __future__ import annotations

# QQ 渠道依赖（首次 channel login 选择 QQ 时安装）
QQ_DEPENDENCIES: list[str] = [
    "aiohttp>=3.9.0",
]


def ensure_qq_dependencies() -> None:
    """检测并安装 QQ 渠道依赖

    在用户首次执行 'illusion-forge channel login' 选择 QQ 时调用。
    已安装则跳过，未安装则通过 pip 安装（与飞书/微信同模式）。
    """
    try:
        import aiohttp  # noqa: F401
        return  # 已安装，跳过
    except ImportError:
        pass

    from illusion_forge.commands.misc import _run_pip_install
    from illusion_forge.config.i18n import t

    print(t("channel_installing_deps", deps=", ".join(QQ_DEPENDENCIES)))
    ok, output = _run_pip_install(QQ_DEPENDENCIES)
    if not ok:
        print(t("channel_deps_failed", error=output[:200]))
        import typer
        raise typer.Exit(1)
    print(t("channel_deps_installed"))
