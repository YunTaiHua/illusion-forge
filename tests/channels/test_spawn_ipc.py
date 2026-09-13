# tests/channels/test_spawn_ipc.py
"""渠道守护进程 IPC spawn 测试"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from illusion_forge.channels import maybe_spawn_channel_daemon


@pytest.fixture(autouse=True)
def _tmp_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """重定向渠道数据目录"""
    data_dir = tmp_path / "channels_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "illusion_forge.config.paths.get_channels_data_dir", lambda: data_dir
    )
    # patch 在 channels/__init__ 模块的引用（若不存在则不报错，仅做额外保险）
    monkeypatch.setattr(
        "illusion_forge.channels.get_channels_data_dir", lambda: data_dir, raising=False
    )


@pytest.fixture(autouse=True)
def _isolate_bg_connect_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """禁用后台连接线程，避免测试退出阶段触发真实 IPC 连接。"""
    monkeypatch.setattr(
        "illusion_forge.channels._start_bg_connect",
        lambda **_kwargs: None,
    )


class _FakeConn:
    """模拟 IPC 连接对象，提供 async close 方法"""

    async def close(self) -> None:
        pass


def test_daemon_running_connects_client(monkeypatch: pytest.MonkeyPatch):
    """守护进程已运行时：连接成功，持有 DaemonClient"""
    from illusion_forge.channels.config import ChannelsConfig, FeishuChannelConfig
    cfg = ChannelsConfig(feishu=FeishuChannelConfig(enabled=True, app_id="x", app_secret="y"))
    monkeypatch.setattr("illusion_forge.channels.load_channels_config", lambda: cfg)

    async def _fake_connect(self):
        self._conn = _FakeConn()  # 模拟真实 connect 设置 _conn
        return True
    monkeypatch.setattr("illusion_forge.daemon_ipc.DaemonClient.connect", _fake_connect)

    async def _fake_register(self):
        return {"type": "ok"}
    monkeypatch.setattr("illusion_forge.daemon_ipc.DaemonClient.register", _fake_register)

    proc, ref = maybe_spawn_channel_daemon()
    assert proc is None
    assert ref is not None
    # ref 内部应持有已连接的 client
    assert ref._client is not None
    assert ref._client.is_connected


def test_fingerprint_mismatch_triggers_restart(monkeypatch: pytest.MonkeyPatch):
    """指纹不匹配时返回 restart_required，杀旧进程并 spawn 新的"""
    from illusion_forge.channels.config import ChannelsConfig, FeishuChannelConfig
    cfg = ChannelsConfig(feishu=FeishuChannelConfig(enabled=True, app_id="x", app_secret="y"))
    monkeypatch.setattr("illusion_forge.channels.load_channels_config", lambda: cfg)

    async def _fake_connect(self):
        self._conn = _FakeConn()
        return True
    monkeypatch.setattr("illusion_forge.daemon_ipc.DaemonClient.connect", _fake_connect)

    async def _fake_register(self):
        # 返回 daemon_pid 以触发杀旧进程路径
        self._daemon_pid = 99999
        return {"type": "restart_required", "daemon_pid": 99999}
    monkeypatch.setattr("illusion_forge.daemon_ipc.DaemonClient.register", _fake_register)

    # 跟踪杀旧进程调用（Unix 用 os.kill；Windows 用 fake ctypes，避免真实 TerminateProcess）
    kill_called: list[bool] = []
    if os.name != "nt":
        def _track_kill(pid, sig):
            kill_called.append(True)
            raise ProcessLookupError(f"测试 mock: PID {pid} 不存在")
        monkeypatch.setattr("os.kill", _track_kill)
    else:
        import ctypes

        class _FakeKernel32:
            """模拟 Windows kernel32，拦截终止调用。"""

            def OpenProcess(self, _access: int, _inherit: bool, _pid: int) -> int:
                return 1

            def TerminateProcess(self, _handle: int, _code: int) -> int:
                kill_called.append(True)
                return 1

            def CloseHandle(self, _handle: int) -> int:
                return 1

        class _FakeWindll:
            kernel32 = _FakeKernel32()

        monkeypatch.setattr(ctypes, "windll", _FakeWindll())

    # 跟踪 subprocess.Popen 调用
    spawn_calls: list[list[str]] = []
    spawn_kwargs: dict = {}

    class _FakeProc:
        pid = 99999

    def _fake_popen(*args, **kwargs):
        spawn_calls.append(args[0] if args else [])
        spawn_kwargs.update(kwargs)
        return _FakeProc()
    monkeypatch.setattr("subprocess.Popen", _fake_popen)

    proc, _client = maybe_spawn_channel_daemon()
    # 验证 spawn 发生（指纹不匹配时应 spawn 新进程）
    assert proc is not None, "指纹不匹配时应 spawn 新进程"
    assert len(spawn_calls) >= 1, "应调用 subprocess.Popen 至少一次"
    # 回归防护：stdout/stderr 必须重定向到 DEVNULL，避免与守护进程内
    # RotatingFileHandler 形成"双写者"（Windows 锁定滚动备份、轮转失败）。
    import subprocess
    assert spawn_kwargs.get("stdout") is subprocess.DEVNULL
    assert spawn_kwargs.get("stderr") is subprocess.DEVNULL
    assert spawn_kwargs.get("stdin") is subprocess.DEVNULL
    # 验证杀旧进程被尝试（Unix: os.kill；Windows: fake TerminateProcess）
    assert kill_called, "指纹不匹配时应尝试杀旧进程"
