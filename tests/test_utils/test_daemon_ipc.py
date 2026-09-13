# tests/test_utils/test_daemon_ipc.py
"""守护进程 IPC 层测试"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from illusion_forge.daemon_ipc import DaemonClient, DaemonServer, DaemonType


@pytest.fixture
def _pipe_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """为测试生成唯一的 pipe/socket 名称"""
    if os.name == "nt":
        # Windows: 每个测试用唯一 pipe 名
        return f"\\\\.\\pipe\\illusion_test_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    else:
        # Unix: 用 tmp_path 下的 socket 文件
        return str(tmp_path / f"test_daemon_{uuid.uuid4().hex[:8]}.sock")


@pytest.mark.asyncio
async def test_server_start_and_client_connect(_pipe_name: str):
    """Server 启动后 Client 能连接"""
    server = DaemonServer(
        daemon_type=DaemonType.CRON,
        daemon_pid=os.getpid(),
        pipe_name=_pipe_name,
    )
    await server.start()
    try:
        client = DaemonClient(daemon_type=DaemonType.CRON, pid=os.getpid(), pipe_name=_pipe_name)
        connected = await client.connect()
        assert connected is True
        await client.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_client_connect_fails_when_no_server(_pipe_name: str):
    """无 Server 时 Client 连接失败"""
    client = DaemonClient(daemon_type=DaemonType.CRON, pid=os.getpid(), pipe_name=_pipe_name)
    connected = await client.connect()
    assert connected is False


@pytest.mark.asyncio
async def test_server_detects_client_disconnect(_pipe_name: str):
    """Server 检测到 Client 断开连接"""
    server = DaemonServer(
        daemon_type=DaemonType.CRON,
        daemon_pid=os.getpid(),
        pipe_name=_pipe_name,
    )
    await server.start()
    try:
        client = DaemonClient(daemon_type=DaemonType.CRON, pid=os.getpid(), pipe_name=_pipe_name)
        await client.connect()
        assert server.connection_count == 1

        await client.close()
        await asyncio.sleep(0.2)  # 等待 server 检测断开
        assert server.connection_count == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_multiple_clients(_pipe_name: str):
    """多个 Client 同时连接"""
    server = DaemonServer(
        daemon_type=DaemonType.CRON,
        daemon_pid=os.getpid(),
        pipe_name=_pipe_name,
    )
    await server.start()
    try:
        clients = []
        for _ in range(3):
            c = DaemonClient(daemon_type=DaemonType.CRON, pid=os.getpid(), pipe_name=_pipe_name)
            await c.connect()
            clients.append(c)
        assert server.connection_count == 3

        await clients[0].close()
        await asyncio.sleep(0.2)
        assert server.connection_count == 2

        for c in clients[1:]:
            await c.close()
        await asyncio.sleep(0.2)
        assert server.connection_count == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ping_pong(_pipe_name: str):
    """Client 发 ping，Server 回 pong（含 daemon_pid）"""
    server = DaemonServer(
        daemon_type=DaemonType.CRON,
        daemon_pid=12345,
        pipe_name=_pipe_name,
    )
    await server.start()
    try:
        client = DaemonClient(daemon_type=DaemonType.CRON, pid=os.getpid(), pipe_name=_pipe_name)
        await client.connect()

        pong = await client.ping(timeout=2.0)
        assert pong is not None
        assert pong["type"] == "pong"
        assert pong["daemon_pid"] == 12345

        await client.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_cron_claim_and_report(_pipe_name: str):
    """cron_claim_pending 领取委托任务，cron_report_result 上报结果"""
    pending: dict[str, Any] = {}
    reported: list[dict[str, Any]] = []

    def on_claim() -> dict[str, Any] | None:
        for job_id, job in list(pending.items()):
            pending.pop(job_id, None)
            return job
        return None

    def on_report(job_id: str, result: dict[str, Any]) -> None:
        reported.append({"job_id": job_id, "result": result})

    server = DaemonServer(
        daemon_type=DaemonType.CRON,
        daemon_pid=12345,
        pipe_name=_pipe_name,
        on_cron_claim=on_claim,
        on_cron_report=on_report,
    )
    await server.start()
    try:
        client = DaemonClient(daemon_type=DaemonType.CRON, pid=os.getpid(), pipe_name=_pipe_name)
        await client.connect()

        # 无任务时领取返回 None
        assert await client.cron_claim_pending(timeout=2.0) is None

        # 有任务时领取返回任务
        pending["job1"] = {"id": "job1", "session_id": "s1", "prompt": "p"}
        job = await client.cron_claim_pending(timeout=2.0)
        assert job is not None
        assert job["id"] == "job1"

        # 上报结果，server 回调收到
        ok = await client.cron_report_result("job1", {"status": "success", "stdout": "ok"}, timeout=2.0)
        assert ok is True
        assert reported == [{"job_id": "job1", "result": {"status": "success", "stdout": "ok"}}]

        await client.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_register_with_fingerprint(_pipe_name: str):
    """Client 发 register（含指纹），Server 回 ok"""
    server = DaemonServer(
        daemon_type=DaemonType.CHANNEL,
        daemon_pid=os.getpid(),
        pipe_name=_pipe_name,
        fingerprint="abc123",
    )
    await server.start()
    try:
        client = DaemonClient(
            daemon_type=DaemonType.CHANNEL,
            pid=os.getpid(),
            fingerprint="abc123",
            pipe_name=_pipe_name,
        )
        await client.connect()

        resp = await client.register()
        assert resp["type"] == "ok"

        await client.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_register_fingerprint_mismatch(_pipe_name: str):
    """指纹不匹配时 Server 回 restart_required"""
    server = DaemonServer(
        daemon_type=DaemonType.CHANNEL,
        daemon_pid=os.getpid(),
        pipe_name=_pipe_name,
        fingerprint="abc123",
    )
    await server.start()
    try:
        client = DaemonClient(
            daemon_type=DaemonType.CHANNEL,
            pid=os.getpid(),
            fingerprint="different",
            pipe_name=_pipe_name,
        )
        await client.connect()

        resp = await client.register()
        assert resp["type"] == "restart_required"

        await client.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_wait_for_no_connections_triggers(_pipe_name: str):
    """所有连接断开后 wait_for_no_connections 返回"""
    server = DaemonServer(
        daemon_type=DaemonType.CRON,
        daemon_pid=os.getpid(),
        pipe_name=_pipe_name,
    )
    await server.start()
    try:
        client = DaemonClient(daemon_type=DaemonType.CRON, pid=os.getpid(), pipe_name=_pipe_name)
        await client.connect()

        # 并行：关闭 client + 等待 server 检测无连接
        async def _close_after_delay():
            await asyncio.sleep(0.3)
            await client.close()

        asyncio.create_task(_close_after_delay())
        await asyncio.wait_for(
            server.wait_for_no_connections(grace_seconds=0.5),
            timeout=3.0,
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_wait_for_no_connections_waits_for_first_connection(_pipe_name: str):
    """没有客户端连接过时 wait_for_no_connections 不返回（防启动竞态）"""
    server = DaemonServer(
        daemon_type=DaemonType.CRON,
        daemon_pid=os.getpid(),
        pipe_name=_pipe_name,
    )
    await server.start()
    try:
        # 守护进程刚启动，没有客户端连接 → 不应返回
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                server.wait_for_no_connections(grace_seconds=0.3),
                timeout=1.0,
            )
        # 确认 _had_connection 仍为 False
        assert not server._had_connection
    finally:
        await server.stop()
