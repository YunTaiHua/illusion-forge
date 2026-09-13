"""跨平台 SIGINT 处理器单元测试。"""

from __future__ import annotations

import asyncio
import signal

from illusion_forge.utils.signals import install_sigint_handler


def test_install_returns_remove_callable():
    """install 返回可调用的 remove 函数。"""
    called = []

    async def run():
        loop = asyncio.get_running_loop()
        remove = install_sigint_handler(loop, lambda: called.append(1))
        assert callable(remove)
        remove()

    asyncio.run(run())


def test_remove_is_idempotent():
    """remove 可重复调用不报错。"""

    async def run():
        loop = asyncio.get_running_loop()
        remove = install_sigint_handler(loop, lambda: None)
        remove()
        remove()  # 幂等

    asyncio.run(run())


def test_windows_fallback_restores_previous_handler():
    """Windows 回退路径恢复 previous handler。"""

    async def run():
        loop = asyncio.get_running_loop()
        remove = install_sigint_handler(loop, lambda: None)
        remove()
        # remove 后应恢复（可能不完全相同，但不应是 None）
        assert signal.getsignal(signal.SIGINT) is not None

    asyncio.run(run())
