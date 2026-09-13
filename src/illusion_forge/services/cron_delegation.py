"""
Cron 委托执行注册表模块
======================

管理「指定会话执行」型 cron 任务的 IPC 委托队列。

核心设计：
    - cron 守护进程（DaemonServer）持有待委托任务队列
    - 正在运行的 Web 主程序通过 cron_claim_pending 轮询领取，
      在自身内存会话中执行（busy 转化、web 列表刷新天然正确），
      执行完通过 cron_report_result 回报结果
    - 领取窗口内无人领取的任务由调度器 reap 回收，回退为子进程
      `illusion-forge -p <prompt> -r <session_id>` 恢复会话执行

数据流：
    scheduler (execute_job)
        │ register_pending_job(job) → Future
        ▼
    cron_delegation 队列 ──claim_pending──▶ Web 主程序
        ▲                                    │ 执行
        └──report_result(job_id, result)─────┘
    scheduler: await future → 组装历史 entry / 超时回退子进程

使用示例：
    >>> fut = register_pending_job({"id": "abc", "prompt": "..."})
    >>> result = await asyncio.wait_for(fut, timeout=330)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# 领取窗口（秒）：任务进入队列后等待主程序领取的最长时间，
# 窗口耗尽后由调度器回收并回退为子进程执行
CLAIM_WINDOW_SECONDS = 30


class _PendingJob:
    """单个待委托任务。"""

    __slots__ = ("deadline", "future", "job")

    def __init__(self, job: dict[str, Any], future: asyncio.Future[Any]) -> None:
        self.job = job
        self.future = future
        self.deadline = time.monotonic() + CLAIM_WINDOW_SECONDS


# 进程内单例（cron 守护进程内唯一）。
# IPC handler 与调度器同属一个事件循环（单线程），无需额外锁。
_pending: dict[str, _PendingJob] = {}
# 委托队列是否由本进程的守护进程服务。cron 守护进程（run_cron_serve）
# 启动时置 True；Web 主程序进程内为 False——它们本地注册的任务无人
# 领取（claim 只发生在守护进程的 IPC handler），必须跳过委托直接回退子进程，
# 否则 execute_job 会白等 330s（手动 run / web run 按钮场景）。
_served = False


def set_served() -> None:
    """标记委托队列已由本进程的守护进程服务（仅 run_cron_serve 调用）。"""
    global _served
    _served = True


def is_served() -> bool:
    """委托队列是否由本进程服务。

    Returns:
        bool: 本进程是 cron 守护进程时返回 True
    """
    return _served


def register_pending_job(job: dict[str, Any]) -> asyncio.Future[Any]:
    """登记一个待委托任务。

    由 cron 调度器（execute_job）在尝试委托前调用。
    返回一个 Future，主程序通过 report_result 上报结果后 resolve；
    领取窗口耗尽（reap_expired）时置为 {"status": "unclaimed"}。

    Args:
        job: 任务字典（须包含 id）

    Returns:
        asyncio.Future: 等待执行结果的 future
    """
    job_id = str(job.get("id", ""))
    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    _pending[job_id] = _PendingJob(job, future)
    logger.info("cron 委托任务入队: id=%s name=%s", job_id, job.get("name", ""))
    return future


def claim_pending() -> dict[str, Any] | None:
    """领取一个待委托任务（原子弹出）。

    由 daemon IPC handler（cron_claim_pending）调用。
    已过领取窗口的任务不返回（由 reap_expired 回收）。

    Returns:
        dict | None: 任务字典，队列为空或已过期时返回 None
    """
    now = time.monotonic()
    for job_id, entry in list(_pending.items()):
        if entry.deadline > now:
            # 弹出并返回
            _pending.pop(job_id, None)
            logger.info("cron 委托任务被领取: id=%s", job_id)
            return entry.job
    return None


def requeue(job_id: str) -> bool:
    """将任务重新入队（主程序回报 not_supported 时）。

    刷新领取截止时间，让其他主程序（或同一主程序下一轮）继续尝试领取。

    Args:
        job_id: 任务 ID

    Returns:
        bool: 任务存在并重新入队返回 True，否则 False
    """
    entry = _pending.get(job_id)
    if entry is None or entry.future.done():
        return False
    entry.deadline = time.monotonic() + CLAIM_WINDOW_SECONDS
    logger.info("cron 委托任务重新入队: id=%s", job_id)
    return True


def report_result(job_id: str, result: dict[str, Any]) -> bool:
    """上报委托执行结果（resolve future）。

    由 daemon IPC handler（cron_report_result）调用。
    - status=not_supported：任务重新入队（供其他主程序领取），不 resolve
    - 其他状态：resolve future
    - future 已 resolve/取消时静默忽略（幂等）

    Args:
        job_id: 任务 ID
        result: 执行结果字典（status/returncode/stdout/stderr 等）

    Returns:
        bool: 任务存在并处理返回 True，否则 False
    """
    entry = _pending.get(job_id)
    if entry is None:
        return False
    if entry.future.done():
        # future 已被 resolve（如 reap 回收后主程序才回报）——幂等忽略
        _pending.pop(job_id, None)
        return True
    if result.get("status") == "not_supported":
        # 主程序无法执行（cwd/会话不匹配）：重新入队等待其他主程序
        requeue(job_id)
        logger.info("cron 委托任务回报 not_supported，重新入队: id=%s", job_id)
        return True
    _pending.pop(job_id, None)
    entry.future.set_result(result)
    logger.info("cron 委托任务回报: id=%s status=%s", job_id, result.get("status"))
    return True


def cancel_pending(job_id: str) -> bool:
    """从队列移除待委托任务（调度器总超时后调用）。

    仅当任务仍未被领取时移除并 resolve unclaimed（调用方据此回退子进程）。
    任务已被领取（在途执行）时返回 False，调用方应标记执行超时而非回退，
    避免子进程与主程序双执行。

    Args:
        job_id: 任务 ID

    Returns:
        bool: 任务在队列中并被移除返回 True；已被领取或不存在返回 False
    """
    entry = _pending.get(job_id)
    if entry is None:
        return False
    _pending.pop(job_id, None)
    if not entry.future.done():
        entry.future.set_result({"status": "unclaimed"})
    return True


def reap_expired() -> list[str]:
    """回收已过领取窗口的任务。

    由调度器 tick 循环调用。回收的任务 future 置
    {"status": "unclaimed"}，调用方据此回退为子进程执行。

    Returns:
        list[str]: 被回收的任务 ID 列表
    """
    now = time.monotonic()
    expired: list[str] = []
    for job_id, entry in list(_pending.items()):
        if entry.deadline <= now:
            _pending.pop(job_id, None)
            if not entry.future.done():
                entry.future.set_result({"status": "unclaimed"})
            expired.append(job_id)
    if expired:
        logger.info("cron 委托领取窗口耗尽，回收 %d 个任务: %s", len(expired), expired)
    return expired


# ---------------------------------------------------------------------------
# 主程序侧客户端辅助（Web 主程序侧）
# ---------------------------------------------------------------------------
# 复用持久 DaemonClient 连接 cron 守护进程，避免频繁创建/关闭临时连接。
# 与 channels_routes 的持久连接模式一致：连接保持活跃，不干扰连接计数语义。

_client_cache: Any = None
_client_cache_lock: asyncio.Lock | None = None


def _get_client_lock() -> asyncio.Lock:
    """获取客户端缓存锁（惰性创建，兼容无事件循环环境）。"""
    global _client_cache_lock
    if _client_cache_lock is None:
        _client_cache_lock = asyncio.Lock()
    return _client_cache_lock


async def get_delegation_client() -> Any | None:
    """获取或创建持久 IPC 客户端（复用连接，不关闭）。

    连接失败（守护进程未运行）时返回 None。连接断开时自动重置以便下次重连。
    使用 asyncio.Lock 串行化创建分支，避免并发请求同时创建多个 client。

    Returns:
        DaemonClient 实例或 None（守护进程未运行）
    """
    global _client_cache
    # 快速路径：连接有效时直接返回（不加锁）
    if _client_cache is not None and _client_cache.is_connected:
        return _client_cache
    # 慢速路径：加锁创建/重连
    lock = _get_client_lock()
    async with lock:
        # double-check（可能在等锁期间已被其他请求创建）
        if _client_cache is not None and _client_cache.is_connected:
            return _client_cache
        import os

        from illusion_forge.daemon_ipc import DaemonClient, DaemonType

        # 关闭旧连接（可能已断开）
        if _client_cache is not None:
            try:
                await _client_cache.close()
            except (OSError, RuntimeError):
                pass
            _client_cache = None
        # 创建新连接
        client = DaemonClient(daemon_type=DaemonType.CRON, pid=os.getpid())
        try:
            connected = await client.connect()
        except (OSError, RuntimeError, ConnectionError):
            return None
        if not connected:
            return None
        _client_cache = client
        return client


async def claim_delegated_job() -> dict[str, Any] | None:
    """领取一个待委托的 cron 任务（轮询拉取，供主程序周期调用）。

    Returns:
        dict | None: 任务字典；守护进程未运行或队列为空时返回 None
    """
    client = await get_delegation_client()
    if client is None:
        return None
    try:
        result = await client.cron_claim_pending(timeout=5.0)
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as exc:
        logger.debug("领取 cron 委托任务失败: %s", exc)
        await _reset_delegation_client()
        return None
    return result if isinstance(result, dict) else None


async def report_delegated_result(job_id: str, result: dict[str, Any]) -> bool:
    """上报 cron 委托任务执行结果。

    Args:
        job_id: 任务 ID
        result: 执行结果字典（status/returncode/stdout/stderr 等）

    Returns:
        bool: 上报成功返回 True（守护进程未运行或上报失败返回 False）
    """
    client = await get_delegation_client()
    if client is None:
        return False
    try:
        return bool(await client.cron_report_result(job_id, result, timeout=5.0))
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as exc:
        logger.debug("上报 cron 委托结果失败: %s", exc)
        await _reset_delegation_client()
        return False


async def _reset_delegation_client() -> None:
    """重置持久连接（操作失败时调用，下次自动重连）。"""
    global _client_cache
    if _client_cache is not None:
        try:
            await _client_cache.close()
        except (OSError, RuntimeError):
            pass
        _client_cache = None
