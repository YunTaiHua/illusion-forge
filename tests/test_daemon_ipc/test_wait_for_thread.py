"""daemon_ipc 方案 B — Future + CloseHandle 测试。"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from illusion_forge.daemon_ipc import _IS_WINDOWS


def test_read_line_timeout_closes_handle():
    """read_line 超时后 CloseHandle 解除线程阻塞。"""
    if not _IS_WINDOWS:
        pytest.skip("仅 Windows 测试")

    async def run():
        import os

        from illusion_forge.daemon_ipc import (
            _win_close_handle,
            _win_connect_pipe,
            _win_connect_to_pipe,
            _win_create_pipe,
            _WindowsPipeConnection,
        )

        pipe_name = f"\\\\.\\pipe\\test_{os.getpid()}_{asyncio.get_event_loop().time()}"
        server_handle = _win_create_pipe(pipe_name)
        try:
            # 先连接客户端，让服务端 pipe 进入 connected 状态
            # （未连接时 ReadFile 立即返回 ERROR_PIPE_LISTENING，不会阻塞）
            client_handle = _win_connect_to_pipe(pipe_name)
            assert client_handle is not None, "客户端连接失败"
            try:
                # 服务端 ConnectNamedPipe 应立即返回（客户端已连接，ERROR_PIPE_CONNECTED）
                connected = await asyncio.to_thread(_win_connect_pipe, server_handle)
                assert connected
                conn = _WindowsPipeConnection(server_handle)
                # 客户端不发送数据，read_line 应阻塞直到超时
                with pytest.raises(asyncio.TimeoutError):
                    await conn.read_line(timeout=0.5)
                # 超时后 handle 应被关闭
                assert conn._closed or conn._handle is None
            finally:
                _win_close_handle(client_handle)
        finally:
            with contextlib.suppress(OSError):
                _win_close_handle(server_handle)

    asyncio.run(run())


def test_stop_does_not_leak_threads():
    """stop() 不泄漏线程（验证 executor 正确关闭）。"""
    if not _IS_WINDOWS:
        pytest.skip("仅 Windows 测试")

    async def run():
        import os

        from illusion_forge.daemon_ipc import _win_create_pipe, _WindowsPipeConnection

        pipe_name = f"\\\\.\\pipe\\test_stop_{os.getpid()}_{asyncio.get_event_loop().time()}"
        server_handle = _win_create_pipe(pipe_name)
        try:
            conn = _WindowsPipeConnection(server_handle)
            # executor 应存在且可关闭
            assert conn._read_executor is not None
            await conn.close()
            # executor 应已关闭
            assert conn._read_executor._shutdown
        finally:
            with contextlib.suppress(OSError):
                from illusion_forge.daemon_ipc import _win_close_handle

                _win_close_handle(server_handle)

    asyncio.run(run())


def test_future_pattern_cancellable():
    """验证 Future + call_soon_threadsafe 模式可被 wait_for 取消。"""

    # 平台无关测试：验证 Future 模式本身可取消
    async def run():
        future: asyncio.Future[str] = asyncio.Future()

        # 模拟一个永远不会完成的读取线程
        # 不提交任何线程，只测试 wait_for 超时
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(future, timeout=0.1)

    asyncio.run(run())
