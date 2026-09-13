"""
cron 守护进程 spawn 逻辑
========================

管理 cron 守护进程的启动和 IPC 连接。

核心设计：
    - 通过 DaemonClient/DaemonServer 管理 IPC 连接，替代 PID 文件 + refs 文件
    - 支持优雅关闭和自动清理旧版 PID/refs 文件

主要组件：
    - spawn_cron_daemon: 启动 cron 守护进程
    - stop_cron_daemon: 停止 cron 守护进程

使用示例：
    >>> client = await spawn_cron_daemon()
    >>> await stop_cron_daemon(client)
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from illusion_forge.config.paths import get_cron_dir
from illusion_forge.services.cron import load_cron_jobs

if TYPE_CHECKING:
    from illusion_forge.daemon_ipc import DaemonClientRef, DaemonType

logger = logging.getLogger(__name__)


def _cleanup_old_pid_files(cron_dir: Path) -> None:
    """清理旧版 PID/refs 文件（一次性迁移）"""
    for name in ("scheduler.pid", "scheduler.refs", "scheduler.refs.lock"):
        try:
            (cron_dir / name).unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Failed to remove stale file %s: %s", name, exc)


def maybe_spawn_cron_daemon(
    *, spawn_if_missing: bool = True,
) -> tuple[subprocess.Popen[bytes] | None, DaemonClientRef | None]:
    """主程序启动时自动拉起 cron 守护进程（IPC 版，异步连接）

    通过 DaemonClient 尝试连接 IPC。连接成功则持有 client 作为引用；
    连接失败则 spawn 子进程，后台线程轮询连接。spawn 后立即返回，
    不阻塞主程序启动。

    Args:
        spawn_if_missing: 连接失败时是否 spawn 新进程。调用方已自行管理守护进程时
            传 False（launcher 已负责 spawn），仅连接持有 ref。

    Returns:
        tuple: (Popen 实例或 None, DaemonClientRef 实例或 None)
    """
    from illusion_forge.daemon_ipc import (
        DaemonClient,
        DaemonClientRef,
        DaemonType,
        connect_and_register,
    )

    jobs = load_cron_jobs()
    enabled = [j for j in jobs if j.get("enabled")]
    if not enabled:
        return None, None

    cron_dir = get_cron_dir()
    client = DaemonClient(daemon_type=DaemonType.CRON, pid=os.getpid())

    # 尝试连接已运行的守护进程（connect+register 在同一事件循环中完成）
    connected, _ = connect_and_register(client)

    if connected:
        # 守护进程已在运行，包装到 ref 并返回
        ref = DaemonClientRef()
        ref.set(client)
        return None, ref

    # 连接失败：清理旧文件并 spawn 新守护进程
    _cleanup_old_pid_files(cron_dir)

    # 不 spawn 模式：只连接（调用方已负责 spawn）
    # 后台线程轮询连接守护进程，连接成功后持有 ref
    if not spawn_if_missing:
        ref = DaemonClientRef()
        _start_bg_connect(
            daemon_type=DaemonType.CRON,
            fingerprint=None,
            ref=ref,
            name="cron 守护进程",
        )
        return None, ref

    # spawn 子进程。stdout/stderr 重定向到 DEVNULL，避免与守护进程内部的
    # RotatingFileHandler（写 cron_scheduler.log）形成"双写者"：父进程若把
    # stdout 指向同一日志文件，子进程会持有一个绕过轮转的 fd，导致 Windows 上
    # 旧的滚动备份被永久锁定且无法删除、轮转也可能因覆盖被锁文件而失败。
    # 日志统一由守护进程内的 RotatingFileHandler 落盘（见 cron_serve.py）。
    creation_flags = 0
    if os.name == "nt":
        creation_flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    try:
        daemon_cwd = str(Path.cwd())
    except (OSError, FileNotFoundError):
        daemon_cwd = str(cron_dir)

    try:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen(
            [sys.executable, "-m", "illusion_forge", "cron", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creation_flags,
            close_fds=True,
            env=env,
            cwd=daemon_cwd,
        )
    except OSError as exc:
        logger.warning("启动 cron 守护进程失败: %s", exc)
        return None, None

    # 异步连接：后台线程轮询，不阻塞主程序
    ref = DaemonClientRef()
    _start_bg_connect(
        daemon_type=DaemonType.CRON,
        fingerprint=None,
        ref=ref,
        name="cron 守护进程",
    )

    return proc, ref


def _start_bg_connect(
    daemon_type: DaemonType,
    fingerprint: str | None,
    ref: DaemonClientRef,
    name: str,
) -> None:
    """启动后台线程轮询连接守护进程（不阻塞主程序）"""
    import threading
    import time

    from illusion_forge.daemon_ipc import DaemonClient, connect_and_register

    def _bg_connect() -> None:
        for _ in range(20):  # 最多 10s
            client = DaemonClient(
                daemon_type=daemon_type,
                pid=os.getpid(),
                fingerprint=fingerprint,
            )
            ok, _ = connect_and_register(client)
            if ok:
                ref.set(client)
                return
            time.sleep(0.5)
        logger.info("%s spawn 后 10s 内未能连接", name)

    t = threading.Thread(target=_bg_connect, daemon=True)
    t.start()


def kill_cron_daemon_by_pid() -> bool:
    """通过 IPC 停止 cron 守护进程

    通过 DaemonClient 连接守护进程，发送 ping 获取 daemon_pid，
    然后终止该进程。成功后清理 IPC 残留文件。

    Returns:
        bool: 成功终止返回 True，无运行中的守护进程返回 False
    """
    import asyncio

    from illusion_forge.daemon_ipc import DaemonClient, DaemonType

    client = DaemonClient(daemon_type=DaemonType.CRON, pid=os.getpid())

    loop = asyncio.new_event_loop()
    try:
        connected = loop.run_until_complete(client.connect())
        if not connected:
            return False

        pong = loop.run_until_complete(client.ping(timeout=2.0))
        if pong is None or "daemon_pid" not in pong:
            loop.run_until_complete(client.close())
            return False

        daemon_pid = pong["daemon_pid"]
        loop.run_until_complete(client.close())
    finally:
        loop.close()

    # 终止守护进程
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(daemon_pid)],
                capture_output=True,
                check=False,
            )
        else:
            import signal
            try:
                os.killpg(os.getpgid(daemon_pid), signal.SIGTERM)  # type: ignore[attr-defined]
            except (ProcessLookupError, PermissionError):
                pass
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("停止 cron 守护进程失败: %s", exc)
        return False

    # 清理 IPC 残留文件（Unix socket）
    cron_dir = get_cron_dir()
    if os.name != "nt":
        try:
            (cron_dir / "cron_daemon.sock").unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Failed to remove stale cron daemon socket: %s", exc)

    logger.info("Stopped cron daemon (pid=%d)", daemon_pid)
    return True
