"""
渠道管理子命令
==============

提供渠道的登录、服务启动、状态查看、启用、禁用和登出功能。

子命令:
    - login: 登录指定渠道
    - serve: 启动渠道服务
    - status: 查看渠道状态
    - enable: 启用渠道
    - disable: 禁用渠道
    - logout: 登出渠道
"""
from __future__ import annotations

import os
import sys

import typer

from illusion_forge.cli import channel_app
from illusion_forge.cli.shared import _ensure_language
from illusion_forge.config.i18n import MESSAGES as _I18N
from illusion_forge.config.i18n import t as _t

# 渠道选项列表（未来新增渠道在此追加）
_CHANNEL_OPTIONS: list[tuple[str, dict[str, str]]] = [
    ("feishu", _I18N.get("channel_feishu_label", {"zh-CN": "飞书", "en-US": "Feishu"})),
    ("weixin", _I18N.get("channel_weixin_label", {"zh-CN": "微信", "en-US": "WeChat"})),
    ("qq", _I18N.get("channel_qq_label", {"zh-CN": "QQ", "en-US": "QQ"})),
]


def _resolve_or_ask_workdir(working_directory: str | None) -> str:
    """解析渠道运行目录：优先参数，否则交互询问（必填）。"""
    raw = working_directory
    if not raw:
        raw = typer.prompt(_t("channel_ask_workdir")).strip()
    if not raw:
        print(_t("channel_workdir_required"), file=sys.stderr)
        raise typer.Exit(1)
    resolved, err = _resolve_channel_workdir(raw)
    if resolved is None:
        print(_t("channel_invalid_workdir", error=err or ""), file=sys.stderr)
        raise typer.Exit(1)
    return resolved


def _feishu_login(working_directory: str | None = None) -> None:
    """飞书渠道配置引导流程

    引导用户完成飞书自建应用的凭据配置，明文存储（按需求不遮掩 App Secret）。
    启用渠道必须配置运行目录（渠道 agent 的工作区锚点）。
    """
    from illusion_forge.channels.config import (
        FeishuChannelConfig,
        FeishuGroupPolicy,
        load_channels_config,
        save_channels_config,
    )
    from illusion_forge.channels.feishu import ensure_feishu_dependencies
    from illusion_forge.config.paths import get_channels_file_path

    # 前置提示：引导去飞书开放平台创建应用
    print(_t("channel_login_intro", url="https://open.feishu.cn/app"))

    # 1. 选平台（国内飞书 / 国际 Lark）
    print(_t("channel_select_domain"))
    print(f"  1. {_t('channel_feishu_domain')}")
    print(f"  2. {_t('channel_lark_domain')}")
    raw = typer.prompt(_t("enter_number"), default="1")
    domain = "feishu" if raw.strip() == "1" else "lark"

    # 2. 输入凭据（明文，不遮掩）
    app_id = input(f"{_t('channel_enter_app_id')}: ").strip()
    if not app_id:
        print(_t("api_key_required"), file=sys.stderr)
        raise typer.Exit(1)
    app_secret = input(f"{_t('channel_enter_app_secret')}: ").strip()
    if not app_secret:
        print(_t("api_key_required"), file=sys.stderr)
        raise typer.Exit(1)

    # 3. 行为选项（带合理默认值，回车即默认）
    def _ask_bool(prompt_key: str, default: bool) -> bool:
        """询问是/否布尔选项，回车取默认"""
        raw_val = typer.prompt(_t(prompt_key), default="Y" if default else "N")
        return raw_val.strip().lower() in ("y", "yes", "是")

    group_isolation = _ask_bool("channel_group_isolation", default=True)
    require_mention = _ask_bool("channel_require_mention", default=True)
    allow_bots = _ask_bool("channel_allow_bots", default=False)
    show_reasoning = _ask_bool("channel_show_reasoning", default=True)

    # 4. 安装依赖（首次配置时自动装 lark-oapi）
    ensure_feishu_dependencies()

    # 5. 保存到 channels.json，置 enabled=true
    cfg = load_channels_config()
    workdir = _resolve_or_ask_workdir(working_directory)
    cfg.feishu = FeishuChannelConfig(
        enabled=True,
        app_id=app_id,
        app_secret=app_secret,
        domain=domain,
        require_mention=require_mention,
        allow_bots=allow_bots,
        group_sessions_per_user=group_isolation,
        group_policy=FeishuGroupPolicy(),
        show_reasoning=show_reasoning,
        working_directory=workdir,
    )
    save_channels_config(cfg)

    path = get_channels_file_path()
    print(_t("channel_saved", path=str(path), channel=_t("channel_feishu_label")))
    print(f"  working directory: {workdir}")


def _weixin_login(working_directory: str | None = None) -> None:
    """微信渠道扫码登录流程

    安装依赖 → 扫码登录（浏览器投射二维码）→ 保存凭据。
    启用渠道必须配置运行目录（渠道 agent 的工作区锚点）。
    """
    from illusion_forge.channels.config import (
        WeixinChannelConfig,
        load_channels_config,
        save_channels_config,
    )
    from illusion_forge.channels.weixin import ensure_weixin_dependencies
    from illusion_forge.config.paths import get_channels_file_path

    # 1. 安装依赖（与飞书同模式，首次配置时自动装）
    ensure_weixin_dependencies()

    # 2. 扫码登录（浏览器投射二维码）
    import asyncio

    from illusion_forge.channels.weixin.ilink_api import qr_login_with_browser
    creds = asyncio.run(qr_login_with_browser())
    if creds is None:
        print(_t("weixin_qr_timeout"), file=sys.stderr)
        raise typer.Exit(1)

    # 3. 保存
    cfg = load_channels_config()
    cfg.weixin = WeixinChannelConfig(
        enabled=True,
        account_id=creds.account_id,
        token=creds.token,
        base_url=creds.base_url,
        user_id=creds.user_id,
        working_directory=_resolve_or_ask_workdir(working_directory),
    )
    save_channels_config(cfg)

    path = get_channels_file_path()
    print(_t("channel_saved", path=str(path), channel=_t("channel_weixin_label")))


def _qq_login(working_directory: str | None = None) -> None:
    """QQ 渠道配置引导流程

    引导用户完成 QQ 开放平台机器人应用的凭据配置。
    启用渠道必须配置运行目录（渠道 agent 的工作区锚点）。
    """
    from illusion_forge.channels.config import (
        QQChannelConfig,
        QQGroupPolicy,
        load_channels_config,
        save_channels_config,
    )
    from illusion_forge.channels.qq import ensure_qq_dependencies
    from illusion_forge.config.paths import get_channels_file_path

    # 前置提示
    print(_t("qq_login_intro"))

    # 1. 输入凭据
    app_id = input(f"{_t('qq_enter_app_id')}: ").strip()
    if not app_id:
        print(_t("api_key_required"), file=sys.stderr)
        raise typer.Exit(1)
    client_secret = input(f"{_t('qq_enter_client_secret')}: ").strip()
    if not client_secret:
        print(_t("api_key_required"), file=sys.stderr)
        raise typer.Exit(1)

    # 2. 行为选项
    def _ask_bool(prompt_key: str, default: bool) -> bool:
        raw_val = typer.prompt(_t(prompt_key), default="Y" if default else "N")
        return raw_val.strip().lower() in ("y", "yes", "是")

    group_isolation = _ask_bool("channel_group_isolation", default=True)
    require_mention = _ask_bool("channel_require_mention", default=True)
    allow_bots = _ask_bool("channel_allow_bots", default=False)
    show_reasoning = _ask_bool("channel_show_reasoning", default=True)

    # 3. 安装依赖
    ensure_qq_dependencies()

    # 4. 保存到 channels.json
    cfg = load_channels_config()
    cfg.qq = QQChannelConfig(
        enabled=True,
        app_id=app_id,
        client_secret=client_secret,
        allow_bots=allow_bots,
        group_sessions_per_user=group_isolation,
        require_mention=require_mention,
        group_policy=QQGroupPolicy(),
        show_reasoning=show_reasoning,
        working_directory=_resolve_or_ask_workdir(working_directory),
    )
    save_channels_config(cfg)

    path = get_channels_file_path()
    print(_t("channel_saved", path=str(path), channel=_t("channel_qq_label")))


@channel_app.command("login")
def channel_login(
    working_directory: str | None = typer.Option(
        None, "--working-directory", "-d",
        help="渠道 agent 运行目录（必填；自动注册为 Web 工作区）/ Channel working directory (required)",
    ),
) -> None:
    """交互式配置消息渠道

    流程：选择渠道 → 配置凭据 → 自动安装依赖 → 保存。
    启用渠道必须配置运行目录（渠道 agent 的工作区锚点）。
    """
    _ensure_language()
    from illusion_forge.config import load_settings

    settings = load_settings()
    lang = settings.ui_language or "en-US"

    # 1. 选择渠道
    print(_t("channel_select"))
    for i, (key, labels) in enumerate(_CHANNEL_OPTIONS, 1):
        label = labels.get(lang, labels.get("en-US", key))
        print(f"  {i}. {label}")
    raw = typer.prompt(_t("enter_number"), default="1")
    try:
        idx = int(raw.strip()) - 1
        if 0 <= idx < len(_CHANNEL_OPTIONS):
            channel_choice = _CHANNEL_OPTIONS[idx][0]
        else:
            print(_t("invalid_selection"), file=sys.stderr)
            raise typer.Exit(1)
    except ValueError:
        print(_t("invalid_selection"), file=sys.stderr)
        raise typer.Exit(1)

    # 2. 分发到具体渠道配置流程
    if channel_choice == "feishu":
        _feishu_login(working_directory)
        return
    elif channel_choice == "weixin":
        _weixin_login(working_directory)
        return
    elif channel_choice == "qq":
        _qq_login(working_directory)
        return


@channel_app.command("serve")
def channel_serve() -> None:
    """启动渠道守护进程（前台运行，监听消息）"""
    from illusion_forge.channels.serve import run_channel_serve
    run_channel_serve()


@channel_app.command("status")
def channel_status() -> None:
    """显示各渠道状态（enabled / 连接 / PID）"""
    from illusion_forge.channels.config import load_channels_config
    from illusion_forge.daemon_ipc import DaemonClient, DaemonType, ping_daemon

    _ensure_language()
    cfg = load_channels_config()

    # 通过 IPC ping 检查守护进程是否在运行，并获取各渠道健康状态
    client = DaemonClient(daemon_type=DaemonType.CHANNEL, pid=os.getpid())
    pong = ping_daemon(client, timeout=2.0)
    channels_status = pong.get("channels", {}) if pong else {}

    print(_t("channel_status_title"))
    for name in ("feishu", "weixin", "qq"):
        enabled = getattr(cfg, name).enabled
        ch_status = channels_status.get(name, {})
        healthy = bool(ch_status.get("healthy", False)) if ch_status else False
        state = _t("channel_connected") if (enabled and healthy) else _t("channel_disconnected")
        print(f"  {name}: enabled={enabled} {state}")


@channel_app.command("enable")
def channel_enable(
    name: str = typer.Argument("feishu", help="渠道名称 / Channel name"),
    working_directory: str | None = typer.Option(
        None, "--working-directory", "-d",
        help="渠道 agent 运行目录（必填；自动注册为 Web 工作区）/ Channel working directory (required)",
    ),
) -> None:
    """启用指定渠道（必须指定运行目录）"""
    from illusion_forge.channels.config import load_channels_config, save_channels_config

    _ensure_language()
    cfg = load_channels_config()

    # 校验凭据
    cred_field = {"feishu": "app_id", "weixin": "account_id", "qq": "app_id"}.get(name)
    channel_cfg = getattr(cfg, name, None)
    if channel_cfg is None:
        print(_t("invalid_selection"), file=sys.stderr)
        raise typer.Exit(1)
    if not getattr(channel_cfg, cred_field or "", ""):
        print(_t("channel_no_creds", channel=name), file=sys.stderr)
        raise typer.Exit(1)

    # 运行目录：启用必须指定（渠道配置已有目录时允许复用）
    if working_directory:
        resolved, err = _resolve_channel_workdir(working_directory)
        if resolved is None:
            print(_t("channel_invalid_workdir", error=err or ""), file=sys.stderr)
            raise typer.Exit(1)
        channel_cfg.working_directory = resolved
    elif not channel_cfg.working_directory:
        print(_t("channel_need_workdir", channel=name), file=sys.stderr)
        raise typer.Exit(1)

    channel_cfg.enabled = True
    save_channels_config(cfg)
    print(_t("channel_enabled", channel=name))
    if working_directory:
        print(f"  working directory: {channel_cfg.working_directory}")


def _resolve_channel_workdir(path: str) -> tuple[str | None, str | None]:
    """校验渠道运行目录并注册为 Web 工作区（与 web 端 start 流程一致）。

    Returns:
        tuple[str | None, str | None]: (规范化目录或 None, 错误信息或 None)
    """
    from illusion_forge.cli.workspace import validate_and_normalize
    from illusion_forge.services import workspace_registry

    resolved, err = validate_and_normalize(path)
    if resolved is None:
        return None, err or "invalid path"
    normalized = str(resolved)
    if not workspace_registry.is_known_workspace(normalized):
        entry, reg_err = workspace_registry.register_workspace(normalized)
        if entry is None:
            return None, reg_err or "register failed"
    return normalized, None


@channel_app.command("disable")
def channel_disable(
    name: str = typer.Argument("feishu", help="渠道名称 / Channel name"),
) -> None:
    """禁用指定渠道"""
    from illusion_forge.channels.config import load_channels_config, save_channels_config

    _ensure_language()
    cfg = load_channels_config()
    if name == "feishu":
        cfg.feishu.enabled = False
        save_channels_config(cfg)
        print(_t("channel_disabled", channel=name))
    elif name == "weixin":
        cfg.weixin.enabled = False
        save_channels_config(cfg)
        print(_t("channel_disabled", channel=name))
    elif name == "qq":
        cfg.qq.enabled = False
        save_channels_config(cfg)
        print(_t("channel_disabled", channel=name))
    else:
        print(_t("invalid_selection"), file=sys.stderr)
        raise typer.Exit(1)


@channel_app.command("logout")
def channel_logout(
    name: str = typer.Argument("feishu", help="渠道名称 / Channel name"),
) -> None:
    """清除指定渠道凭据"""
    from illusion_forge.channels.config import (
        FeishuChannelConfig,
        WeixinChannelConfig,
        load_channels_config,
        save_channels_config,
    )

    _ensure_language()
    cfg = load_channels_config()
    if name == "feishu":
        cfg.feishu = FeishuChannelConfig()  # 重置为默认（清空凭据 + disabled）
        save_channels_config(cfg)
        print(_t("channel_logout_done", channel=name))
    elif name == "weixin":
        cfg.weixin = WeixinChannelConfig()  # 重置为默认（清空凭据 + disabled）
        save_channels_config(cfg)
        print(_t("channel_logout_done", channel=name))
    elif name == "qq":
        from illusion_forge.channels.config import QQChannelConfig
        cfg.qq = QQChannelConfig()  # 重置为默认（清空凭据 + disabled）
        save_channels_config(cfg)
        print(_t("channel_logout_done", channel=name))
    else:
        print(_t("invalid_selection"), file=sys.stderr)
        raise typer.Exit(1)
