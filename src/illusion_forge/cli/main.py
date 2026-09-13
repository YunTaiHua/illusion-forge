"""
主命令回调
==========

处理 IllusionForge 的主命令逻辑：工作目录切换、默认启动 Web UI、
无头（print）模式执行、会话恢复与设置持久化。

主要功能:
    - 默认（无子命令、无 -p）启动 Web UI
    - 无头打印模式（-p/--print），供 cron 与脚本调用
    - 工作目录切换（基于 settings 或 --cwd 参数）
    - 渠道和 Cron 任务的自动激活
    - 会话恢复（-c/--continue、-r/--resume，仅配合 -p）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from illusion_forge.cli import _version_callback, app
from illusion_forge.cli.shared import _ensure_language
from illusion_forge.cli.workspace import validate_and_normalize
from illusion_forge.config.i18n import t as _t


def _persist_session_overrides(
    *,
    model: str | None,
    effort: str | None,
    max_turns: int | None,
    permission_mode: str | None,
) -> None:
    """把 CLI 显式传入的 model/effort/max_turns/permission_mode 持久化到 settings.json。

    仅持久化显式传入的值；cron 通过环境变量 ILLUSION_PERMISSION_MODE 临时指定
    的权限模式不经此处，避免子进程污染全局权限配置。
    """
    if not any(v is not None for v in (model, effort, max_turns, permission_mode)):
        return
    from illusion_forge.config import load_settings, save_settings

    settings = load_settings()
    if model is not None:
        settings.model = model
    if effort is not None:
        settings.effort = effort
    if max_turns is not None:
        settings.max_turns = max_turns
    if permission_mode is not None:
        from illusion_forge.permissions.modes import PermissionMode

        settings.permission.mode = PermissionMode(permission_mode)
    save_settings(settings)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
    # --- Session ---
    continue_session: bool = typer.Option(
        False,
        "--continue",
        "-c",
        help="Continue the most recent conversation in the current directory (with -p)",
        rich_help_panel="Session",
    ),
    resume: str | None = typer.Option(
        None,
        "--resume",
        "-r",
        help="Resume a conversation by session ID (with -p)",
        rich_help_panel="Session",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Set a display name for this session",
        rich_help_panel="Session",
    ),
    # --- Model & Effort ---
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model ID in env_N.model_N format (e.g. 'env_1.model_2')",
        rich_help_panel="Model & Effort",
    ),
    effort: str | None = typer.Option(
        None,
        "-e", "--effort",
        help="Effort level (low, medium, high, xhigh, max). Persists to settings.",
        rich_help_panel="Model & Effort",
    ),
    max_turns: int | None = typer.Option(
        None,
        "-t", "--max-turns",
        help="Maximum agentic turns. Persists to settings.",
        rich_help_panel="Model & Effort",
    ),
    # --- Output ---
    print_mode: str | None = typer.Option(
        None,
        "--print",
        "-p",
        help="Headless mode: print response and exit. Pass your prompt as the value: -p 'your prompt'",
        rich_help_panel="Output",
    ),
    output_format: str | None = typer.Option(
        None,
        "--output-format",
        help="Output format with --print: text (default), json, or stream-json",
        rich_help_panel="Output",
    ),
    # --- Permissions ---
    permission_mode: str | None = typer.Option(
        None,
        "--permission-mode",
        help="Permission mode: default, plan, full_auto, or yolo",
        rich_help_panel="Permissions",
    ),
    dangerously_skip_permissions: bool = typer.Option(
        False,
        "--dangerously-skip-permissions",
        help="Bypass all permission checks (only for sandboxed environments)",
        rich_help_panel="Permissions",
    ),
    # --- Advanced ---
    cwd: str | None = typer.Option(
        None,
        "--cwd",
        help="Working directory for the session",
        hidden=True,
    ),
) -> None:
    """主入口函数：默认启动 Web UI，或以无头模式运行单个提示词

    运行模式：
    - Web UI（默认，等价于 `illusion-forge forge`）
    - 无头打印模式（-p/--print），可配合 -c/-r 恢复会话

    Args:
        ctx: Typer 上下文对象
        version: 显示版本号选项
        continue_session: 继续最近会话选项（仅 -p）
        resume: 通过会话 ID 恢复会话选项（仅 -p）
        name: 会话显示名称
        model: 模型别名或完整模型 ID
        effort: 会话努力级别
        max_turns: 最大代理轮次数
        print_mode: 打印模式提示词
        output_format: 输出格式
        permission_mode: 权限模式
        dangerously_skip_permissions: 跳过权限检查
        cwd: 会话工作目录
    """
    # 读取settings.json中的working_directory字段，切换工作目录（子命令也适用）
    from illusion_forge.config import load_settings
    settings = load_settings()
    # 仅在用户未显式指定 --cwd 时，才使用 settings.working_directory
    if cwd is None and settings.working_directory:
        cwd = settings.working_directory
    if cwd:
        working_dir = Path(cwd).expanduser().resolve()
        if working_dir.exists() and working_dir.is_dir():
            os.chdir(working_dir)
            cwd = str(working_dir)
        else:
            import logging
            logging.getLogger(__name__).warning(
                _t("cwd_invalid", path=cwd)
            )

    if ctx.invoked_subcommand is not None:  # 如果调用了子命令，直接返回
        return

    if dangerously_skip_permissions:  # 如果跳过权限检查
        permission_mode = "full_auto"  # 设置为完全自动模式

    # -c/-r 仅在无头模式下有意义（Web UI 自带会话列表）
    if (continue_session or resume is not None) and print_mode is None:
        print(_t("continue_requires_print"), file=sys.stderr)
        raise typer.Exit(1)

    # 默认路径：启动 Web UI（守护进程激活与渠道感知由 launch_web 负责）
    if print_mode is None:
        _persist_session_overrides(
            model=model, effort=effort, max_turns=max_turns, permission_mode=permission_mode,
        )
        from illusion_forge.cli.forge import launch_web
        launch_web(model=model)
        return

    # --- 无头打印模式 ---
    prompt = print_mode.strip()
    if not prompt:
        print(_t("print_requires_prompt"), file=sys.stderr)
        raise typer.Exit(1)
    # resume="" 在 print 模式下报错（先校验，避免持久化副作用）
    if resume == "":
        print(_t("session_resume_requires_id"), file=sys.stderr)
        raise typer.Exit(1)

    # 渠道自动激活：有 enabled 渠道时 spawn 守护进程
    _daemon_client = None
    try:
        from illusion_forge.channels import maybe_spawn_channel_daemon
        _, _daemon_client = maybe_spawn_channel_daemon()
    except (OSError, RuntimeError) as exc:
        import logging
        logging.getLogger(__name__).warning("渠道自动激活失败: %s", exc)

    # cron 自动激活：有启用任务时 spawn 守护进程
    _cron_client = None
    try:
        from illusion_forge.services.cron_spawn import maybe_spawn_cron_daemon
        _, _cron_client = maybe_spawn_cron_daemon()
    except (OSError, RuntimeError) as exc:
        import logging
        logging.getLogger(__name__).warning("cron 自动激活失败: %s", exc)

    # cron 上下文：通过环境变量 ILLUSION_PERMISSION_MODE 临时指定权限模式，
    # 不持久化到 settings.json（避免 cron 子进程污染全局权限配置）。
    # CLI --permission-mode 仍用于用户主动切换并持久化。
    effective_permission_mode = permission_mode or os.environ.get("ILLUSION_PERMISSION_MODE")
    _persist_session_overrides(
        model=model, effort=effort, max_turns=max_turns, permission_mode=permission_mode,
    )

    import asyncio

    from illusion_forge.ui.headless import run_print_mode

    try:
        asyncio.run(
            run_print_mode(
                prompt=prompt,
                output_format=output_format or "text",
                cwd=cwd,
                model=model,
                permission_mode=effective_permission_mode,
                max_turns=max_turns,
                effort=effort,
                continue_session=continue_session,
                resume=resume,
                name=name,
            )
        )
    finally:
        # 关闭 IPC 连接（OS 也会在进程退出时自动关闭）
        for ref in (_cron_client, _daemon_client):
            if ref is not None:
                ref.close()


@app.command("set")
def set_cmd(
    working_directory: str | None = typer.Argument(None, help="工作目录路径"),
) -> None:
    """设置工作目录

    无参数时显示当前工作目录；有参数时校验并设置（目录不存在则新建）。
    """
    from illusion_forge.config import load_settings, save_settings

    _ensure_language()
    settings = load_settings()

    if working_directory is None:
        if settings.working_directory:
            print(_t("set_current_working_directory", path=settings.working_directory))
        else:
            print(_t("set_no_working_directory"))
            print(_t("set_usage"))
        return

    resolved, err = validate_and_normalize(working_directory)
    if resolved is None and err:
        print(_t("set_invalid_path", path=working_directory), file=sys.stderr)
        raise typer.Exit(1)
    if resolved is None:
        print(_t("set_no_working_directory"))
        print(_t("set_usage"))
        return

    settings.working_directory = str(resolved)
    save_settings(settings)
    print(_t("set_saved", path=str(resolved)))
