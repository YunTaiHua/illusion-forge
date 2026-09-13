"""渠道守护进程 PID 文件管理
==========================

通过 PID 文件避免重复启动渠道守护进程。

函数说明：
    - read_pid: 读取 PID 文件
    - write_pid: 写入 PID 文件
    - is_process_alive: 检测进程是否存活
    - PidFile: PID 文件管理封装
"""
from __future__ import annotations

import os  # 进程检测
from pathlib import Path  # 路径处理

from illusion_forge.utils.atomic_write import atomic_write_text  # 原子写入工具


def read_pid(path: Path) -> int | None:
    """读取 PID 文件中的进程 ID

    Args:
        path: PID 文件路径

    Returns:
        int | None: PID，文件不存在或损坏时返回 None
    """
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def write_pid(path: Path, pid: int) -> None:
    """写入 PID 到文件

    Args:
        path: PID 文件路径
        pid: 进程 ID
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, str(pid))


def is_process_alive(pid: int) -> bool:
    """检测指定 PID 的进程是否存活

    跨平台实现：
    - Windows：用 ctypes.OpenProcess 探测（os.kill 在 Windows 上不可靠，
      对不存在的进程会抛出混乱异常「returned a result with an exception set」）
    - Unix：用 os.kill(pid, 0) 发送 0 信号探测

    Args:
        pid: 进程 ID

    Returns:
        bool: 存活返回 True
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        # Windows：用 OpenProcess 探测，返回句柄非零即存在
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)  # 发送 0 信号探测
    except ProcessLookupError:
        return False  # 进程不存在
    except PermissionError:
        return True  # 进程存在但无权限（仍视为存活）
    except (OverflowError, OSError):
        # OverflowError: PID 超 C long 范围
        # OSError: 其他系统调用错误
        return False
    return True


class PidFile:
    """PID 文件管理封装

    封装 PID 读写与存活检测的组合操作。

    Attributes:
        path: PID 文件路径
    """

    def __init__(self, path: Path) -> None:
        """初始化

        Args:
            path: PID 文件路径
        """
        self.path = path  # PID 文件路径

    def is_running(self) -> bool:
        """检测 PID 文件指向的守护进程是否正在运行

        Returns:
            bool: PID 文件存在且对应进程存活时返回 True
        """
        pid = read_pid(self.path)
        if pid is None:
            return False
        return is_process_alive(pid)

    def acquire(self, pid: int) -> None:
        """写入 PID

        Args:
            pid: 要记录的进程 ID
        """
        write_pid(self.path, pid)

    def release(self) -> None:
        """删除 PID 文件"""
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass  # 已删除，忽略
