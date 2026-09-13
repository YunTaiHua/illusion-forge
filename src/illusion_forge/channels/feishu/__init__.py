"""飞书渠道模块
================

提供 IllusionForge 的飞书（Feishu / Lark）消息渠道实现。

子模块：
    - adapter: WS 长连接与事件分发
    - messaging: 消息收发
    - session_map: 飞书会话存储
    - commands: 飞书侧斜杠命令

本包内部延迟导入 lark_oapi，确保未安装 SDK 时主程序不崩溃。
"""
from __future__ import annotations

# 飞书渠道依赖（首次 channel login 时安装）
FEISHU_DEPENDENCIES: list[str] = ["lark-oapi>=1.4.0"]


def ensure_feishu_dependencies() -> None:
    """检测并安装飞书渠道依赖

    在用户首次执行 'illusion-forge channel login' 选择飞书时调用。
    已安装则跳过，未安装则通过 pip 安装。

    安装失败时打印错误并退出（typer.Exit）。
    """
    try:
        import lark_oapi  # noqa: F401
        return  # 已安装，跳过
    except ImportError:
        pass

    from illusion_forge.commands.misc import _run_pip_install
    from illusion_forge.config.i18n import t

    print(t("channel_installing_deps", deps=", ".join(FEISHU_DEPENDENCIES)))
    ok, output = _run_pip_install(FEISHU_DEPENDENCIES)
    if not ok:
        print(t("channel_deps_failed", error=output[:200]))
        import typer
        raise typer.Exit(1)
    print(t("channel_deps_installed"))
