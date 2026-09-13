"""Web 端 Cron 定时任务 REST 路由模块
=====================================

供 web 前端通过 HTTP 管理 cron 定时任务（注册表 CRUD + 调度器状态 + 手动触发）。

与 env_routes.py / channels_routes.py 职责分离：本模块只处理 cron 任务的
创建、读取、更新、删除、手动运行，以及调度器运行状态查询。

任务持久化在 cron 注册表文件（~/.illusion/cron/jobs.json），调度器守护进程
每 30s tick 从磁盘重新加载，因此本模块直接读写注册表即可被调度器感知，
无需额外通知守护进程；仅在创建任务时确保守护进程已拉起。

路由清单：
    - GET  /api/cron/status                 查询调度器运行状态与任务统计
    - GET  /api/cron/jobs                   列出全部任务（含禁用）
    - POST /api/cron/jobs                   创建任务（创建后确保调度器运行）
    - PATCH /api/cron/jobs/{identifier}     更新任务（schedule/prompt/enabled 等）
    - DELETE /api/cron/jobs/{identifier}    删除任务
    - POST /api/cron/jobs/{identifier}/run  手动触发执行任务
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from illusion_forge.services.cron import (
    delete_cron_job,
    get_cron_job,
    get_cron_job_by_name,
    load_cron_jobs,
    upsert_cron_job,
    validate_cron_expression,
)

logger = logging.getLogger(__name__)

# 手动运行返回的 stdout/stderr 截断长度（避免大输出撑爆 HTTP 响应）
_RUN_OUTPUT_LIMIT = 2000

# 手动运行中的任务 ID 集合（web server 进程内）。
# run 端点执行期间标记，完成后移除；GET /api/cron/jobs 附带该集合，
# 前端据此禁用运行中任务的 run 按钮（退出设置弹窗再进入仍保持禁用，
# 避免同一任务被重复手动触发）。
_running_jobs: set[str] = set()


class CreateCronJobRequest(BaseModel):
    """创建 cron 任务请求体。

    Attributes:
        name: 任务名称（可选，缺省自动生成）
        schedule: 5 字段 cron 表达式（本地时间，必填）
        prompt: 触发时执行的提示词（必填）
        recurring: 是否重复执行（默认 True）
        enabled: 是否启用（默认 True）
        delete_after_run: 一次性任务执行后是否自动删除
        deliver_to: 投递目标列表（channel:chat_id 格式，可选）
        session_id: 指定会话执行（可选；缺省 = 独立新会话）
        cwd: 任务执行的工作区目录（可选；缺省 = 默认工作区，需已注册）
    """

    name: str | None = None
    schedule: str
    prompt: str
    recurring: bool = True
    enabled: bool = True
    delete_after_run: bool = False
    deliver_to: list[str] = []
    session_id: str | None = None
    cwd: str | None = None


class UpdateCronJobRequest(BaseModel):
    """更新 cron 任务请求体（仅提供需要修改的字段）。

    Attributes:
        name: 新任务名称（与其他任务重名时返回 400）
        schedule: 新 cron 表达式
        prompt: 新提示词
        recurring: 是否重复执行
        enabled: 是否启用
        delete_after_run: 一次性任务执行后是否自动删除
        deliver_to: 投递目标列表
        session_id: 指定会话执行（None 显式清除）
        cwd: 任务执行的工作区目录（须为已注册工作区；None 保留原值）
    """

    name: str | None = None
    schedule: str | None = None
    prompt: str | None = None
    recurring: bool | None = None
    enabled: bool | None = None
    delete_after_run: bool | None = None
    deliver_to: list[str] | None = None
    cwd: str | None = None
    session_id: str | None = None


def register_cron_routes(app: FastAPI, host_config: Any | None = None) -> None:
    """注册 cron 定时任务 HTTP 路由到 FastAPI app。

    Args:
        app: FastAPI 应用实例
        host_config: 宿主配置（保留参数以与 env_routes 签名对齐，当前未使用）
    """

    @app.get("/api/cron/status")
    async def get_cron_status() -> dict[str, Any]:
        """查询调度器运行状态与任务统计。

        Returns:
            dict: 包含 running/pid/total_jobs/enabled_jobs 的状态字典
        """
        from illusion_forge.services.cron_scheduler import scheduler_status

        status = scheduler_status()
        return {
            "running": bool(status.get("running", False)),
            "pid": status.get("pid"),
            "total_jobs": int(status.get("total_jobs", 0)),
            "enabled_jobs": int(status.get("enabled_jobs", 0)),
        }

    @app.get("/api/cron/jobs")
    async def list_cron_jobs() -> dict[str, Any]:
        """列出全部 cron 任务（含禁用任务）及手动运行中的任务 ID。

        Returns:
            dict: {"jobs": [任务字典, ...], "running_jobs": [任务 ID, ...]}
        """
        return {
            "jobs": load_cron_jobs(),
            "running_jobs": sorted(_running_jobs),
        }

    @app.get("/api/cron/sessions")
    async def list_cron_sessions(cwd: str | None = None) -> dict[str, Any]:
        """列出指定工作区目录下的项目会话（前端 dropdown 数据源）。

        Args:
            cwd: 工作区目录（可选；缺省 = 默认工作区，未知目录回退默认）

        Returns:
            dict: {"sessions": [{session_id, summary, message_count, updated_at}, ...]}
        """
        from illusion_forge.services.session_storage import list_session_snapshots
        from illusion_forge.services.workspace_registry import (
            get_default_workspace,
            is_known_workspace,
            normalize_workspace_path,
        )

        target_cwd = normalize_workspace_path(cwd) if cwd and is_known_workspace(cwd) else get_default_workspace()
        return {"sessions": await asyncio.to_thread(list_session_snapshots, target_cwd, 100)}

    @app.get("/api/cron/channel_sessions")
    async def list_cron_channel_sessions() -> dict[str, Any]:
        """列出各渠道的活跃会话（deliver_to dropdown 数据源）。

        仅返回 enabled 渠道的活跃会话；渠道未启用或无会话时为空列表。

        Returns:
            dict: {"channels": {渠道名: [{chat_id, user_name, chat_type, last_active}, ...]}}
        """
        from illusion_forge.channels.config import load_channels_config
        from illusion_forge.prompts.channel_hints import list_active_sessions

        cfg = load_channels_config()
        channels: dict[str, Any] = {}
        for name in ("feishu", "weixin", "qq"):
            channel_cfg = getattr(cfg, name, None)
            if channel_cfg is None or not getattr(channel_cfg, "enabled", False):
                continue
            sessions = list_active_sessions(name, cfg, limit=20)
            channels[name] = [
                {
                    "chat_id": s.chat_id,
                    "user_name": s.user_name,
                    "chat_type": s.chat_type,
                    "last_active": s.last_active,
                }
                for s in sessions
            ]
        return {"channels": channels}

    @app.post("/api/cron/jobs")
    async def create_cron_job(req: CreateCronJobRequest) -> dict[str, Any]:
        """创建 cron 任务并持久化。

        校验 cron 表达式与提示词必填；创建成功后确保调度器守护进程已拉起
        （spawn 失败不影响任务创建结果）。

        Args:
            req: 创建请求体

        Returns:
            dict: {"id": str, "job": 完整任务字典}
        """
        schedule = req.schedule.strip()
        if not validate_cron_expression(schedule):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid cron expression: {req.schedule!r}\n"
                    "Use 5-field format: minute hour day month weekday\n"
                    "Examples: '*/5 * * * *' (every 5 min), '0 9 * * 1-5' (weekdays 9am)"
                ),
            )
        prompt = req.prompt.strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")

        # 任务执行目录：优先请求指定（须为已注册工作区，未知目录 400 与
        # update 语义一致），缺省默认工作区。多目录空间下任务的 cwd 决定
        # 其会话归属目录与 web 端委托匹配。
        from illusion_forge.services.workspace_registry import (
            get_default_workspace,
            is_known_workspace,
            normalize_workspace_path,
        )

        if req.cwd:
            if not is_known_workspace(req.cwd):
                raise HTTPException(status_code=400, detail=f"Unknown workspace: {req.cwd}")
            job_cwd = normalize_workspace_path(req.cwd)
        else:
            job_cwd = get_default_workspace()

        job_data: dict[str, Any] = {
            "schedule": schedule,
            "prompt": prompt,
            "recurring": req.recurring,
            "enabled": req.enabled,
            "delete_after_run": req.delete_after_run,
            "cwd": job_cwd,
            "deliver_to": req.deliver_to,
        }
        if req.name is not None and req.name.strip():
            job_data["name"] = req.name.strip()
        # 指定会话执行（可选）：留空 = 独立新会话（默认行为）
        if req.session_id:
            job_data["session_id"] = req.session_id.strip()

        job_id = upsert_cron_job(job_data)

        # 确保调度器守护进程已运行（创建任务后自动拉起，与 cron_tool 行为一致）
        # 使用 asyncio.to_thread 避免阻塞事件循环；失败仅记录日志
        try:
            from illusion_forge.services.cron_spawn import maybe_spawn_cron_daemon

            await asyncio.to_thread(maybe_spawn_cron_daemon)
        except (ImportError, OSError, RuntimeError, asyncio.TimeoutError) as exc:
            logger.warning("cron 守护进程拉起失败: %s", exc)

        job = get_cron_job(job_id)
        return {"id": job_id, "job": job if job is not None else job_data}

    @app.patch("/api/cron/jobs/{identifier}")
    async def update_cron_job(
        identifier: str,
        req: UpdateCronJobRequest,
    ) -> dict[str, Any]:
        """更新 cron 任务并持久化。

        仅修改请求中提供的字段；name 与其他任务重名时返回 400；
        schedule 更新后自动重算 next_run。

        Args:
            identifier: 任务 ID 或名称
            req: 更新请求体

        Returns:
            dict: {"success": True, "job": 更新后的任务字典}
        """
        job = get_cron_job(identifier)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Cron job not found: {identifier}")

        # name 重命名：检查与现有任务重名（排除自身）
        if req.name is not None:
            new_name = req.name.strip()
            if not new_name:
                raise HTTPException(status_code=400, detail="name cannot be empty")
            existing = get_cron_job_by_name(new_name)
            if existing is not None and existing.get("id") != job.get("id"):
                raise HTTPException(status_code=400, detail=f"Cron job name already exists: {new_name}")
            job["name"] = new_name

        if req.schedule is not None:
            schedule = req.schedule.strip()
            if not validate_cron_expression(schedule):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid cron expression: {req.schedule!r}",
                )
            job["schedule"] = schedule

        if req.prompt is not None:
            prompt = req.prompt.strip()
            if not prompt:
                raise HTTPException(status_code=400, detail="prompt cannot be empty")
            job["prompt"] = prompt

        if req.recurring is not None:
            job["recurring"] = req.recurring

        if req.enabled is not None:
            job["enabled"] = req.enabled

        if req.delete_after_run is not None:
            job["delete_after_run"] = req.delete_after_run

        if req.deliver_to is not None:
            job["deliver_to"] = req.deliver_to

        # 指定会话执行：仅当请求显式提供该字段时才更新（None 显式清除）
        if "session_id" in req.model_fields_set:
            new_session_id = (req.session_id or "").strip()
            if new_session_id:
                job["session_id"] = new_session_id
            else:
                job.pop("session_id", None)

        # 任务执行目录：仅当请求显式提供时才更新（须为已注册工作区）
        if "cwd" in req.model_fields_set and req.cwd:
            from illusion_forge.services.workspace_registry import (
                is_known_workspace,
                normalize_workspace_path,
            )

            if is_known_workspace(req.cwd):
                job["cwd"] = normalize_workspace_path(req.cwd)
            else:
                raise HTTPException(status_code=400, detail=f"Unknown workspace: {req.cwd}")

        upsert_cron_job(job)
        return {"success": True, "job": get_cron_job(identifier)}

    @app.delete("/api/cron/jobs/{identifier}")
    async def remove_cron_job(identifier: str) -> dict[str, Any]:
        """删除 cron 任务。

        Args:
            identifier: 任务 ID 或名称

        Returns:
            dict: {"success": True}
        """
        if not delete_cron_job(identifier):
            raise HTTPException(status_code=404, detail=f"Cron job not found: {identifier}")
        return {"success": True}

    @app.post("/api/cron/jobs/{identifier}/run")
    async def run_cron_job(identifier: str) -> dict[str, Any]:
        """手动触发执行 cron 任务。

        在独立子进程中执行任务提示词（`illusion-forge -p`），请求等待执行完成，
        返回结果摘要（stdout/stderr 截断）。

        Args:
            identifier: 任务 ID 或名称

        Returns:
            dict: 执行结果摘要 {status, returncode, started_at, ended_at, stdout, stderr}
        """
        from illusion_forge.services.cron_scheduler import execute_job

        job = get_cron_job(identifier)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Cron job not found: {identifier}")
        if not job.get("prompt"):
            raise HTTPException(status_code=400, detail=f"Job has no prompt: {identifier}")

        # 标记运行中：执行期间 GET /api/cron/jobs 返回的 running_jobs 包含
        # 该任务，前端 run 按钮保持禁用（退出设置弹窗再进入也不可重复触发）
        _running_jobs.add(job_id := str(job.get("id", identifier)))
        try:
            entry = await execute_job(job)
        finally:
            _running_jobs.discard(job_id)
        return {
            "status": entry.get("status", "unknown"),
            "returncode": entry.get("returncode", "?"),
            "started_at": entry.get("started_at", ""),
            "ended_at": entry.get("ended_at", ""),
            "stdout": str(entry.get("stdout", ""))[-_RUN_OUTPUT_LIMIT:],
            "stderr": str(entry.get("stderr", ""))[-_RUN_OUTPUT_LIMIT:],
        }
