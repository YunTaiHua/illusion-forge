"""
Cron 定时任务管理子命令
=======================

提供 Cron 调度任务的启动、停止、状态查看、列表、切换、历史和日志功能。

子命令:
    - start: 启动 Cron 调度器
    - stop: 停止 Cron 调度器
    - status: 查看 Cron 调度器状态
    - list: 列出所有定时任务
    - toggle: 切换定时任务启用/禁用状态
    - history: 查看任务执行历史
    - logs: 查看任务日志
"""
from __future__ import annotations

import typer

from illusion_forge.cli import cron_app
from illusion_forge.cli.shared import _ensure_language
from illusion_forge.config.i18n import t as _t


@cron_app.command("start")
def cron_start() -> None:
    """启动 cron 调度器"""
    from illusion_forge.services.cron_spawn import maybe_spawn_cron_daemon

    proc, _ = maybe_spawn_cron_daemon()
    if proc is None:
        # 已有守护进程在运行，或无启用任务
        from illusion_forge.services.cron_scheduler import is_scheduler_running
        if is_scheduler_running():
            print(_t("cron_already_running"))
        else:
            print(_t("cron_jobs_none"))
    else:
        print(_t("cron_started", pid=proc.pid))


@cron_app.command("stop")
def cron_stop() -> None:
    """停止 cron 调度器"""
    from illusion_forge.services.cron_spawn import kill_cron_daemon_by_pid

    if kill_cron_daemon_by_pid():
        print(_t("cron_stopped"))
    else:
        print(_t("cron_not_running"))


@cron_app.command("status")
def cron_status_cmd() -> None:
    """显示 cron 调度器状态和任务统计"""
    from illusion_forge.services.cron_scheduler import scheduler_status

    status = scheduler_status()
    state = _t("cron_state_running") if status["running"] else _t("cron_state_stopped")
    print(f"Scheduler: {state}" + (f" (pid={status['pid']})" if status["pid"] else ""))
    print(f"Jobs: {status['enabled_jobs']} {_t('cron_enabled')} / {status['total_jobs']} total")
    print(f"Log: {status['log_file']}")


@cron_app.command("serve")
def cron_serve() -> None:
    """cron 守护进程主入口（前台运行）"""
    from illusion_forge.services.cron_serve import run_cron_serve

    _ensure_language()
    run_cron_serve()


@cron_app.command("list")
def cron_list_cmd() -> None:
    """列出所有 cron 任务"""
    from illusion_forge.services.cron import load_cron_jobs

    jobs = load_cron_jobs()
    if not jobs:
        print(_t("cron_jobs_none"))
        return
    never = _t("cron_never")
    na = _t("cron_na")
    for job in jobs:
        enabled = "+" if job.get("enabled", True) else "-"
        name = job.get("name", job.get("id", "?"))
        schedule = job.get("schedule", "?")
        recurring = _t("cron_recurring") if job.get("recurring", True) else _t("cron_oneshot")

        last = job.get("last_run", never)
        if last != never:
            last = last[:19]
        last_status = job.get("last_status", "")
        status_indicator = f" [{last_status}]" if last_status else ""

        next_run = job.get("next_run", na)
        if next_run != na:
            next_run = next_run[:19]

        errors = job.get("consecutive_errors", 0)
        error_str = f" [{_t('cron_errors', n=errors)}]" if errors > 0 else ""

        print(f"  [{enabled}] {name}  {schedule} ({recurring})")
        print(f"        {_t('cron_prompt_label')}: {job.get('prompt', '?')[:60]}")
        print(f"        {_t('cron_last_label')}: {last}{status_indicator}  {_t('cron_next_label')}: {next_run}{error_str}")


@cron_app.command("toggle")
def cron_toggle_cmd(
    name: str = typer.Argument(..., help="Job name or ID"),
    enabled: bool = typer.Argument(..., help="true to enable, false to disable"),
) -> None:
    """启用或禁用 cron 任务"""
    from illusion_forge.services.cron import set_job_enabled

    if not set_job_enabled(name, enabled):
        print(_t("cron_job_not_found", name=name))
        raise typer.Exit(1)
    state = _t("cron_enabled") if enabled else _t("cron_disabled")
    print(_t("cron_job_state", name=name, state=state))


@cron_app.command("run")
def cron_run_cmd(
    name: str = typer.Argument(..., help="Job name or ID"),
) -> None:
    """手动触发执行 cron 任务"""
    import asyncio

    from illusion_forge.services.cron import get_cron_job
    from illusion_forge.services.cron_scheduler import execute_job

    job = get_cron_job(name)
    if job is None:
        print(_t("cron_job_not_found", name=name))
        raise typer.Exit(1)

    prompt = job.get("prompt", "")
    if not prompt:
        print(_t("cron_no_prompt", name=name))
        raise typer.Exit(1)

    print(_t("cron_running_job", name=name))
    entry = asyncio.run(execute_job(job))
    status = entry.get("status", "unknown")
    rc = entry.get("returncode", "?")
    print(_t("cron_finished", status=status, rc=rc))

    stdout = entry.get("stdout", "").strip()
    stderr = entry.get("stderr", "").strip()
    if stdout:
        print(f"{_t('cron_output')}\n{stdout}")
    if stderr and status != "success":
        print(f"{_t('cron_error')}\n{stderr}")


@cron_app.command("history")
def cron_history_cmd(
    name: str | None = typer.Argument(None, help="Filter by job name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of entries"),
) -> None:
    """显示 cron 执行历史记录"""
    from illusion_forge.services.cron_scheduler import load_history

    entries = load_history(limit=limit, job_name=name)
    if not entries:
        print(_t("cron_no_history"))
        return
    for entry in entries:
        ts = entry.get("started_at", "?")[:19]
        status = entry.get("status", "?")
        rc = entry.get("returncode", "?")
        job_name = entry.get("name", "?")
        prompt_preview = entry.get("prompt", "")[:40]
        print(f"  {ts}  {job_name}  {status} (rc={rc})")
        if prompt_preview:
            print(f"    {_t('cron_prompt_label')}: {prompt_preview}")
        stderr = entry.get("stderr", "").strip()
        if stderr and status != "success":
            for line in stderr.splitlines()[:3]:
                print(f"    {_t('cron_error')} {line}")


@cron_app.command("logs")
def cron_logs_cmd(
    lines: int = typer.Option(30, "--lines", "-n", help="Number of lines"),
) -> None:
    """显示 cron 调度器日志"""
    from illusion_forge.config.paths import get_logs_dir

    log_path = get_logs_dir() / "cron_scheduler.log"
    if not log_path.exists():
        print(_t("cron_no_log"))
        return
    content = log_path.read_text(encoding="utf-8", errors="replace")
    tail = content.splitlines()[-lines:]
    for line in tail:
        print(line)
