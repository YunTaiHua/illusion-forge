"""微信渠道模块
================

提供 IllusionForge 的微信（个人微信 iLink Bot）消息渠道实现。

子模块：
    - ilink_api: iLink Bot API 客户端（扫码/收发/打字）
    - adapter: 长轮询、准入控制、context_token
    - session_map: 微信会话存储
    - commands: 微信侧斜杠命令

本包内部延迟导入 aiohttp/cryptography/qrcode，确保未安装依赖时主程序不崩溃。
"""
from __future__ import annotations

# 微信渠道依赖（首次 channel login 选择微信时安装）
WEIXIN_DEPENDENCIES: list[str] = [
    "aiohttp>=3.9.0",
    "cryptography>=42.0.0",
    "qrcode>=7.4.0",
]


def ensure_weixin_dependencies() -> None:
    """检测并安装微信渠道依赖

    在用户首次执行 'illusion-forge channel login' 选择微信时调用。
    已安装则跳过，未安装则通过 pip 安装（与飞书同模式，不强制安装）。
    """
    try:
        import aiohttp  # noqa: F401
        import cryptography  # noqa: F401
        import qrcode  # noqa: F401
        return  # 已安装，跳过
    except ImportError:
        pass

    from illusion_forge.commands.misc import _run_pip_install
    from illusion_forge.config.i18n import t

    print(t("channel_installing_deps", deps=", ".join(WEIXIN_DEPENDENCIES)))
    ok, output = _run_pip_install(WEIXIN_DEPENDENCIES)
    if not ok:
        print(t("channel_deps_failed", error=output[:200]))
        import typer
        raise typer.Exit(1)
    print(t("channel_deps_installed"))
