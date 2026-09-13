"""渠道守护进程 PID 文件管理测试。"""
from __future__ import annotations

import os
from pathlib import Path

from illusion_forge.channels.pid import (
    PidFile,
    is_process_alive,
    read_pid,
    write_pid,
)


def test_write_and_read_pid(tmp_path: Path):
    """写 PID 后能读回。"""
    path = tmp_path / "feishu.pid"
    write_pid(path, 12345)
    assert read_pid(path) == 12345


def test_read_missing_pid_returns_none(tmp_path: Path):
    """文件不存在时返回 None。"""
    path = tmp_path / "missing.pid"
    assert read_pid(path) is None


def test_read_corrupted_pid_returns_none(tmp_path: Path):
    """文件内容非数字时返回 None。"""
    path = tmp_path / "bad.pid"
    path.write_text("not a number", encoding="utf-8")
    assert read_pid(path) is None


def test_is_process_alive_for_current_process():
    """当前进程的 PID 存活。"""
    assert is_process_alive(os.getpid()) is True


def test_is_process_alive_for_dead_pid():
    """不存在的 PID 视为已死。"""
    # PID 0xFFFFFFFF 几乎不可能存在
    assert is_process_alive(0xFFFFFFFF) is False


def test_pid_file_is_running_no_file(tmp_path: Path):
    """PID 文件不存在时 is_running 为 False。"""
    pf = PidFile(tmp_path / "feishu.pid")
    assert pf.is_running() is False


def test_pid_file_is_running_with_dead_pid(tmp_path: Path):
    """PID 文件存在但进程已死时 is_running 为 False。"""
    path = tmp_path / "feishu.pid"
    write_pid(path, 0xFFFFFFFF)  # 死 PID
    pf = PidFile(path)
    assert pf.is_running() is False


def test_pid_file_acquire_and_release(tmp_path: Path):
    """acquire 写入 PID，release 删除文件。"""
    path = tmp_path / "feishu.pid"
    pf = PidFile(path)
    pf.acquire(99999)
    assert read_pid(path) == 99999
    pf.release()
    assert not path.exists()


def test_pid_file_release_missing_is_noop(tmp_path: Path):
    """release 已删除的文件不报错。"""
    pf = PidFile(tmp_path / "gone.pid")
    pf.release()  # 不应抛异常
