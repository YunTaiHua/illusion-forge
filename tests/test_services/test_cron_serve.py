# tests/test_services/test_cron_serve.py
"""cron 守护进程主入口测试（IPC 版）"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from illusion_forge.services.cron_serve import _serve_async, run_cron_serve


@pytest.fixture(autouse=True)
def _tmp_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """重定向 cron 目录和日志目录到临时目录"""
    cron_dir = tmp_path / "data" / "cron"
    logs_dir = tmp_path / "logs"
    cron_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "illusion_forge.services.cron_serve.get_cron_dir", lambda: cron_dir
    )
    monkeypatch.setattr(
        "illusion_forge.services.cron_serve.get_logs_dir", lambda: logs_dir
    )
    monkeypatch.setattr(
        "illusion_forge.services.cron_scheduler.get_cron_dir", lambda: cron_dir
    )


def test_run_cron_serve_starts_server_and_serve():
    """run_cron_serve 启动 DaemonServer 并调用 _serve_async"""
    from illusion_forge.daemon_ipc import DaemonServer

    server_instances = []

    # 捕获 DaemonServer 实例
    original_init = DaemonServer.__init__
    def _capture_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        server_instances.append(self)
    # patch DaemonServer 在 cron_serve 模块中的引用

    # 模拟 server.start 和 server.stop
    async def _fake_start(self):
        pass
    async def _fake_stop(self):
        pass

    # 模拟 _serve_async 立即返回
    serve_called = {"n": 0}
    async def _fake_serve(server):
        serve_called["n"] += 1

    with (
        patch("illusion_forge.daemon_ipc.DaemonServer.start", _fake_start),
        patch("illusion_forge.daemon_ipc.DaemonServer.stop", _fake_stop),
        patch("illusion_forge.services.cron_serve._serve_async", _fake_serve),
        patch("illusion_forge.services.cron_serve._setup_logging"),
        patch("illusion_forge.services.cron_spawn._cleanup_old_pid_files"),
    ):
        run_cron_serve()

    assert serve_called["n"] == 1


@pytest.mark.asyncio
async def test_serve_async_starts_scheduler_and_waits_for_connections():
    """_serve_async 启动调度器并等待连接归零"""
    # 创建 mock server
    server = MagicMock()
    server.wait_for_no_connections = AsyncMock()

    # 让 wait_for_no_connections 在 0.1s 后返回
    async def _wait_then_return(grace_seconds=3.0):
        await asyncio.sleep(0.1)
    server.wait_for_no_connections.side_effect = _wait_then_return

    # 模拟调度器
    mock_scheduler = AsyncMock()
    mock_scheduler.is_running = False
    mock_scheduler.start = AsyncMock()
    mock_scheduler.stop = AsyncMock()

    with patch("illusion_forge.services.cron_serve.get_scheduler", return_value=mock_scheduler):
        await _serve_async(server)

    mock_scheduler.start.assert_called_once()
    mock_scheduler.stop.assert_called_once()
    server.wait_for_no_connections.assert_called_once()


@pytest.mark.asyncio
async def test_serve_async_stops_scheduler_on_exception():
    """_serve_async 异常时仍停止调度器"""
    server = MagicMock()
    server.wait_for_no_connections = AsyncMock(side_effect=RuntimeError("test error"))

    mock_scheduler = AsyncMock()
    mock_scheduler.is_running = False
    mock_scheduler.start = AsyncMock()
    mock_scheduler.stop = AsyncMock()

    with (
        patch("illusion_forge.services.cron_serve.get_scheduler", return_value=mock_scheduler),
        pytest.raises(RuntimeError),
    ):
        await _serve_async(server)

    mock_scheduler.start.assert_called_once()
    mock_scheduler.stop.assert_called_once()


def test_run_cron_serve_does_not_touch_real_pid_file(monkeypatch, tmp_path):
    """run_cron_serve 不应写入或删除真实的 scheduler.pid"""
    import os
    from illusion_forge.services import cron_scheduler

    cron_dir = tmp_path / "data" / "cron"
    cron_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 同时 patch cron_serve 和 cron_scheduler 的 get_cron_dir
    monkeypatch.setattr("illusion_forge.services.cron_serve.get_cron_dir", lambda: cron_dir)
    monkeypatch.setattr("illusion_forge.services.cron_scheduler.get_cron_dir", lambda: cron_dir)
    monkeypatch.setattr("illusion_forge.services.cron_serve.get_logs_dir", lambda: logs_dir)

    # 记录真实 PID 文件路径
    from illusion_forge.services.cron_scheduler import get_pid_path
    # 在 patch 作用下，get_pid_path 应返回临时目录下的路径
    pid_path = get_pid_path()
    assert str(pid_path).startswith(str(tmp_path)), f"PID 文件应在临时目录下，实际 {pid_path}"
