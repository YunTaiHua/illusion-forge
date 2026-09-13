"""
信号处理模块
============

本模块提供跨平台的 SIGINT 处理器安装，支持优雅响应 Ctrl+C。

主要功能：
    - install_sigint_handler: 安装 SIGINT 处理器，返回 remove() 清理函数
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Callable


def install_sigint_handler(
    loop: asyncio.AbstractEventLoop, handler: Callable[[], None]
) -> Callable[[], None]:
    """安装 SIGINT 处理器，返回用于清理的 remove() 函数。

    优先使用 loop.add_signal_handler（Unix）；失败时回退到 signal.signal
    （Windows ProactorEventLoop 不支持 add_signal_handler）。

    Args:
        loop: 当前事件循环
        handler: 收到 SIGINT 时调用的无参回调

    Returns:
        remove: 移除已安装处理器的函数，幂等可重复调用
    """
    try:
        loop.add_signal_handler(signal.SIGINT, handler)

        def remove() -> None:
            with contextlib.suppress(RuntimeError):
                loop.remove_signal_handler(signal.SIGINT)

        return remove
    except RuntimeError:
        # Windows ProactorEventLoop 回退路径
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda signum, frame: handler())

        def remove() -> None:
            with contextlib.suppress(RuntimeError):
                signal.signal(signal.SIGINT, previous)

        return remove
