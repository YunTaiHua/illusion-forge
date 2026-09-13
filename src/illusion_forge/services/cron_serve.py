"""
cron 守护进程主入口
===================

实现 'illusion-forge cron serve' 命令：启动 CronScheduler 后台循环。

核心设计：
    - 通过 DaemonServer 监控 IPC 连接数，连接归零时自动退出
    - 日志输出到文件（RotatingFileHandler）和控制台（StreamHandler）

主要组件：
    - run_cron_serve: 启动 cron 守护进程的主函数

使用示例：
    >>> asyncio.run(run_cron_serve())
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

from illusion_forge.config.paths import get_cron_dir, get_logs_dir
from illusion_forge.services.cron_scheduler import get_scheduler, remove_pid, write_pid

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """配置日志：RotatingFileHandler + StreamHandler
    父进程 spawn 时 stdout/stderr 已重定向到 DEVNULL，避免"双写者"问题
    （见 cron_spawn.py 的 DEVNULL 说明），日志统一由本 handler 落盘。
    轮转策略：单文件最大 10MB，保留 5 个备份（总计约 60MB），避免无限增长
    """
    from logging.handlers import RotatingFileHandler

    log_path = get_logs_dir() / "cron_scheduler.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)
    logger.info("cron 守护进程启动，日志文件: %s", log_path)

    # stdout 已不重定向到日志文件，补一个 excepthook 把未捕获异常写入日志，
    # 保留崩溃可追溯性。
    def _handle_uncaught(exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger().error(
            "cron 守护进程未捕获异常", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _handle_uncaught


def run_cron_serve() -> None:
    """cron 守护进程主入口（IPC 版）

    启动 DaemonServer 监听连接，运行 _serve_async 等待连接归零。
    """
    from illusion_forge.daemon_ipc import DaemonServer, DaemonType
    from illusion_forge.services.cron_spawn import _cleanup_old_pid_files

    cron_dir = get_cron_dir()
    _cleanup_old_pid_files(cron_dir)

    _setup_logging()

    # 注入 cron 委托执行回调：主程序通过 IPC 领取待委托任务 / 上报执行结果。
    # cron_delegation 与调度器同属本守护进程事件循环，队列操作无需加锁。
    # 同时标记委托队列已由本进程服务（非 daemon 进程跳过委托直接回退子进程，
    # 避免手动 run / web run 按钮在本地注册任务后无人领取白等 330s）。
    from illusion_forge.services.cron_delegation import (
        claim_pending,
        report_result,
        set_served,
    )

    set_served()

    server = DaemonServer(
        daemon_type=DaemonType.CRON,
        daemon_pid=os.getpid(),
        on_cron_claim=claim_pending,
        on_cron_report=report_result,
    )

    # 写入 PID 文件，供 is_scheduler_running() 跨进程检测守护进程状态。
    # 60e2e33 将 PID 管理从 CronScheduler._run_loop 迁移到此处，但当时遗漏了调用。
    write_pid(os.getpid())

    loop: asyncio.AbstractEventLoop | None = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.start())
        loop.run_until_complete(_serve_async(server))
    except KeyboardInterrupt:
        pass
    finally:
        if loop is not None:
            loop.run_until_complete(server.stop())
            loop.close()
        remove_pid()


async def _serve_async(server: Any) -> None:
    """异步主循环：启动调度器 + 等待连接归零

    Args:
        server: DaemonServer 实例
    """
    scheduler = get_scheduler()
    stop_event = asyncio.Event()

    # 启动调度器
    await scheduler.start()

    # 启动连接监控
    async def _monitor() -> None:
        await server.wait_for_no_connections(grace_seconds=3.0)
        stop_event.set()

    monitor_task = asyncio.create_task(_monitor(), name="cron-connection-monitor")
    stop_wait_task = asyncio.create_task(stop_event.wait())

    try:
        # 同时等待 stop_event 或 monitor_task 完成
        # monitor 异常时需要传播，使 _serve_async 退出
        done, _ = await asyncio.wait(
            [stop_wait_task, monitor_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        # monitor 异常结束时传播异常
        if monitor_task in done and not monitor_task.cancelled():
            exc = monitor_task.exception()
            if exc is not None:
                raise exc
    finally:
        monitor_task.cancel()
        stop_wait_task.cancel()
        for t in (monitor_task, stop_wait_task):
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("cron serve 等待 task 完成时捕获异常: %s", exc, exc_info=exc)
        await scheduler.stop()
