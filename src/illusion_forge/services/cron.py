"""
Cron 任务注册表模块
==================

提供定时任务的增删改查功能。

数据模型字段：
    - id: 唯一标识符（UUID）
    - name: 人类可读的任务名称
    - schedule: 标准 5 字段 cron 表达式（本地时间）
    - prompt: 每次触发时执行的提示词
    - enabled: 是否启用
    - recurring: 是否重复执行（False 为一次性任务）
    - delete_after_run: 执行后是否自动删除
    - cwd: 工作目录
    - created_at: 创建时间（本地时间 ISO 格式）
    - updated_at: 最后更新时间
    - next_run: 下次运行时间
    - last_run: 上次运行时间
    - last_status: 上次执行状态 ("success" | "failed" | "timeout" | "error")
    - consecutive_errors: 连续错误次数（成功时重置为 0）

主要函数：
    - load_cron_jobs: 加载任务列表（自动迁移旧格式）
    - save_cron_jobs: 持久化任务列表
    - validate_cron_expression: 验证 cron 表达式
    - next_run_time: 计算下次运行时间（本地时间）
    - upsert_cron_job: 插入或更新任务
    - delete_cron_job: 删除任务
    - get_cron_job: 按 ID 获取任务
    - get_cron_job_by_name: 按名称获取任务
    - set_job_enabled: 启用/禁用任务
    - mark_job_run: 标记执行结果并更新状态
    - remove_expired_jobs: 清理过期任务

使用示例：
    >>> from illusion_forge.services.cron import upsert_cron_job, load_cron_jobs
    >>> upsert_cron_job({"name": "daily-report", "schedule": "0 9 * * *", "prompt": "生成日报"})
    >>> jobs = load_cron_jobs()
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from croniter import croniter

from illusion_forge.config.paths import get_cron_registry_path
from illusion_forge.utils.atomic_write import atomic_write_text

# 存储格式版本号，用于未来迁移
_STORE_VERSION = 1


def _generate_id() -> str:
    """生成短 UUID 作为任务 ID。"""
    return uuid.uuid4().hex[:12]


def _now_local() -> datetime:
    """返回本地时间（无时区信息），对齐用户本地时间。"""
    # 通过 UTC → 本地时区 → 移除 tzinfo 的路径获取无时区的本地时间，
    # 避免 datetime.now() 不带 tz 参数（DTZ005）。
    return datetime.now(UTC).astimezone().replace(tzinfo=None, microsecond=0)


def _now_iso() -> str:
    """返回本地时间的 ISO 格式字符串。"""
    return _now_local().isoformat()


def _normalize_job(job: dict[str, Any]) -> dict[str, Any]:
    """规范化单个任务字段，处理旧格式迁移。

    旧格式使用 'command' 字段，新格式统一为 'prompt'。
    旧格式缺少 'id' 字段，自动生成。
    """
    # 旧格式 command -> 新格式 prompt
    if "command" in job and "prompt" not in job:
        job["prompt"] = job.pop("command")

    # 缺少 id 则自动生成
    if not job.get("id"):
        job["id"] = _generate_id()

    # 确保必要字段存在
    job.setdefault("name", job["id"])
    job.setdefault("enabled", True)
    job.setdefault("recurring", True)
    job.setdefault("delete_after_run", False)
    job.setdefault("consecutive_errors", 0)
    job.setdefault("deliver_to", [])         # 投递目标列表 list[str]
    job.setdefault("origin_channel", "")     # 来源渠道
    job.setdefault("chat_id", "")            # 来源会话（记录用，投递时由 deliver_to 自动解析）
    job.setdefault("created_at", _now_iso())
    job.setdefault("updated_at", job["created_at"])

    return job


def load_cron_jobs() -> list[dict[str, Any]]:
    """加载已保存的 Cron 任务列表。

    自动处理旧格式迁移（command -> prompt，缺少 id 等）。
    返回规范化后的任务列表。
    """
    path = get_cron_registry_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    # 兼容旧格式：直接是列表
    if isinstance(data, list):
        jobs = data
    # 新格式：带 version 的字典
    elif isinstance(data, dict):
        jobs = data.get("jobs", [])
        if not isinstance(jobs, list):
            return []
    else:
        return []

    return [_normalize_job(job) for job in jobs if isinstance(job, dict)]


def save_cron_jobs(jobs: list[dict[str, Any]]) -> None:
    """将 Cron 任务列表持久化到磁盘。

    使用带版本号的新格式存储。
    """
    path = get_cron_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    store = {"version": _STORE_VERSION, "jobs": jobs}
    atomic_write_text(path, json.dumps(store, indent=2, ensure_ascii=False) + "\n")


def validate_cron_expression(expression: str) -> bool:
    """验证是否为有效的 cron 表达式。"""
    if not expression or not isinstance(expression, str):
        return False
    return croniter.is_valid(expression.strip())


def next_run_time(expression: str, base: datetime | None = None) -> datetime:
    """返回 cron 表达式的下次运行时间（本地时间）。

    Args:
        expression: 5 字段 cron 表达式
        base: 基准时间，默认为当前本地时间

    Returns:
        datetime: 下次运行的本地时间
    """
    base = base or _now_local()
    return croniter(expression, base).get_next(datetime)


def upsert_cron_job(job: dict[str, Any]) -> str:
    """插入或替换一个 Cron 任务。

    自动生成 id（如未提供），设置默认值，计算下次运行时间。
    返回任务的 id。

    Args:
        job: 任务字典，至少包含 schedule 和 prompt

    Returns:
        str: 任务 ID
    """
    # 确保有 id
    if not job.get("id"):
        job["id"] = _generate_id()

    # 规范化字段
    job = _normalize_job(job)
    job["updated_at"] = _now_iso()

    # 设置首次创建时间
    if "created_at" not in job:
        job["created_at"] = _now_iso()

    # 如果是新的一次性任务且 delete_after_run 未显式设置为 True，自动设置为 True
    if not job.get("recurring", True) and not job.get("delete_after_run", False):
        job["delete_after_run"] = True

    # 验证并计算下次运行时间
    schedule = job.get("schedule", "")
    if validate_cron_expression(schedule):
        job["next_run"] = next_run_time(schedule).isoformat()

    # 按 id 和 name 去重，保留更新
    job_id = job["id"]
    job_name = job.get("name")
    jobs = [
        j for j in load_cron_jobs()
        if j.get("id") != job_id and j.get("name") != job_name
    ]
    jobs.append(job)
    jobs.sort(key=lambda item: str(item.get("name", "")))

    save_cron_jobs(jobs)
    return str(job_id)


def delete_cron_job(identifier: str) -> bool:
    """按 ID 或名称删除一个 Cron 任务。

    先按 id 匹配，再按 name 匹配。
    如果找到并删除则返回 True，否则返回 False。
    """
    jobs = load_cron_jobs()
    filtered = [
        j for j in jobs
        if j.get("id") != identifier and j.get("name") != identifier
    ]
    if len(filtered) == len(jobs):
        return False
    save_cron_jobs(filtered)
    return True


def get_cron_job(identifier: str) -> dict[str, Any] | None:
    """按 ID 或名称返回一个 Cron 任务。

    先按 id 匹配，再按 name 匹配。
    """
    for job in load_cron_jobs():
        if job.get("id") == identifier or job.get("name") == identifier:
            return job
    return None


def get_cron_job_by_name(name: str) -> dict[str, Any] | None:
    """按名称返回一个 Cron 任务。"""
    for job in load_cron_jobs():
        if job.get("name") == name:
            return job
    return None


def set_job_enabled(identifier: str, enabled: bool) -> bool:
    """启用或禁用 Cron 任务。

    按 id 或 name 查找任务。
    如果找到则更新并返回 True，否则返回 False。
    """
    jobs = load_cron_jobs()
    for job in jobs:
        if job.get("id") == identifier or job.get("name") == identifier:
            job["enabled"] = enabled
            job["updated_at"] = _now_iso()
            save_cron_jobs(jobs)
            return True
    return False


def mark_job_run(
    identifier: str,
    *,
    success: bool,
    status: str | None = None,
) -> None:
    """任务执行后更新状态并重新计算下次运行时间。

    自动处理：
    - 更新 last_run 和 last_status
    - 成功时重置 consecutive_errors 为 0
    - 失败时递增 consecutive_errors
    - 一次性任务（recurring=False）执行后禁用
    - delete_after_run 任务执行后标记待删除

    Args:
        identifier: 任务 ID 或名称
        success: 是否执行成功
        status: 自定义状态字符串（默认 success/failed）
    """
    jobs = load_cron_jobs()
    now = _now_local()

    for job in jobs:
        if job.get("id") != identifier and job.get("name") != identifier:
            continue

        # 更新执行状态
        job["last_run"] = now.isoformat()
        job["last_status"] = status or ("success" if success else "failed")
        job["updated_at"] = now.isoformat()

        # 连续错误计数
        if success:
            job["consecutive_errors"] = 0
        else:
            job["consecutive_errors"] = job.get("consecutive_errors", 0) + 1

        # 一次性任务执行后禁用
        if not job.get("recurring", True):
            job["enabled"] = False

        # 标记 delete_after_run
        if job.get("delete_after_run") and not job.get("recurring", True):
            job["_pending_delete"] = True

        # 重新计算下次运行时间（仅对重复任务）
        schedule = job.get("schedule", "")
        if job.get("recurring", True) and validate_cron_expression(schedule):
            job["next_run"] = next_run_time(schedule, now).isoformat()

        save_cron_jobs(jobs)
        return


def remove_expired_jobs() -> list[str]:
    """清理标记为待删除的一次性任务。

    返回被删除的任务 ID 列表。
    """
    jobs = load_cron_jobs()
    remaining: list[dict[str, Any]] = []
    removed_ids: list[str] = []

    for job in jobs:
        if job.get("_pending_delete"):
            removed_ids.append(job.get("id", ""))
        else:
            remaining.append(job)

    if removed_ids:
        save_cron_jobs(remaining)

    return removed_ids


def get_consecutive_error_count(identifier: str) -> int:
    """获取任务的连续错误次数。"""
    job = get_cron_job(identifier)
    if job is None:
        return 0
    result: int = job.get("consecutive_errors", 0)
    return result
