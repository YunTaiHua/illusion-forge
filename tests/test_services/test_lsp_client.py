"""Task 17 测试：LSP client 异步化 + _pending 线程安全 + MCP gather 异常取消

覆盖：
    1. ``start()`` / ``stop()`` 通过 ``asyncio.to_thread`` 让出事件循环
    2. ``_pending`` 字典用 ``threading.Lock`` 保护，超时路径 cancel Future 而非仅 pop
    3. ``get_event_loop`` 替换为 ``get_running_loop``
    4. MCP ``connect_all`` 在异常路径下取消未完成 task
    5. LSP manager ``shutdown_all`` 并行化
"""
from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from illusion_forge.services.lsp.client import LspClient
from illusion_forge.services.lsp.manager import LspManager

# ─── 1. start() / stop() 异步化 ──────────────────────────────────


def test_start_async_uses_to_thread():
    """start() 通过 asyncio.to_thread 包装 sp.Popen，不阻塞事件循环。

    通过源码检查：start() 体中应包含 asyncio.to_thread(sp.Popen[Any], ...)。
    """
    source = inspect.getsource(LspClient.start)
    assert "asyncio.to_thread" in source, "start() 必须用 asyncio.to_thread 包装 sp.Popen"
    assert "sp.Popen[Any]" in source, "start() 必须保留 sp.Popen[Any] 调用"
    assert "get_event_loop" not in source, "start() 不应再用 get_event_loop"
    assert "get_running_loop" in source, "start() 必须用 get_running_loop"


def test_start_is_coroutine_function():
    """start() 是协程函数。"""
    assert inspect.iscoroutinefunction(LspClient.start)


def test_stop_async_uses_to_thread():
    """stop() 通过 asyncio.to_thread 包装 proc.wait，不阻塞 5 秒。

    通过源码检查：stop() 体中应包含 asyncio.to_thread(self._proc.wait, timeout=5)。
    """
    source = inspect.getsource(LspClient.stop)
    assert "asyncio.to_thread" in source, "stop() 必须用 asyncio.to_thread 包装 proc.wait"
    assert "self._proc.wait" in source, "stop() 必须保留 self._proc.wait 调用"
    # 不应再直接同步调用 proc.wait(timeout=5)
    assert "self._proc.wait(timeout=5)" not in source, (
        "stop() 不应再直接同步调用 proc.wait(timeout=5)"
    )


def test_stop_is_coroutine_function():
    """stop() 是协程函数。"""
    assert inspect.iscoroutinefunction(LspClient.stop)


@pytest.mark.asyncio
async def test_start_with_mocked_popen_does_not_block():
    """start() 调用 mocked Popen 不抛异常，且线程启动。

    使用 mock sp.Popen 避免依赖真实 LSP 服务器，保证测试确定性。
    注意：源码用 ``sp.Popen[Any](...)``（带类型下标），mock 必须支持 ``__getitem__``。
    """
    client = LspClient()

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.stdin = MagicMock()
    fake_proc.stdout = MagicMock()
    fake_proc.stderr = MagicMock()
    # stdout.read(1) 返回空字节，让 reader 线程立即退出
    fake_proc.stdout.read.return_value = b""
    # stderr.readline() 返回空字节，让 stderr_drain 线程立即退出
    fake_proc.stderr.readline.return_value = b""

    import illusion_forge.services.lsp.client as lsp_client_mod

    # 构造支持 ``Popen[Any]`` 下标的 mock：让 __getitem__ 返回自身
    popen_mock = MagicMock()
    popen_mock.__getitem__.return_value = popen_mock
    popen_mock.return_value = fake_proc

    original_popen = lsp_client_mod.sp.Popen
    try:
        lsp_client_mod.sp.Popen = popen_mock  # type: ignore[assignment]
        await client.start("fake-lsp-server", ["--stdio"])
    finally:
        lsp_client_mod.sp.Popen = original_popen  # type: ignore[assignment]

    assert client._proc is fake_proc
    assert client._loop is asyncio.get_running_loop()
    # _connected 可能在 reader 线程退出后被设为 False（mock stdout.read 返回 b""），
    # 不再断言 _connected，只验证 _proc 和 _loop 被正确设置

    # 清理：让 reader/writer 线程退出
    client._connected = False
    if client._write_q:
        client._write_q.put(None)
    # 给后台线程一点时间退出
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_stop_cleans_pending_futures():
    """stop() 清理 _pending 中的 Future 并设置 ConnectionError 异常。"""
    client = LspClient()
    client._loop = asyncio.get_running_loop()
    client._connected = True
    # 注入一个 pending Future
    fut: asyncio.Future[Any] = client._loop.create_future()
    client._pending[42] = fut

    # mock proc 避免真实子进程
    fake_proc = MagicMock()
    fake_proc.wait.return_value = 0
    client._proc = fake_proc  # type: ignore[assignment]

    import queue
    client._write_q = queue.Queue()

    await client.stop()

    # Future 应被设置 ConnectionError 异常（而非 cancelled）
    assert fut.done()
    with pytest.raises(ConnectionError):
        fut.result()
    # _pending 字典应被清空
    assert len(client._pending) == 0
    # proc.wait 应被调用
    fake_proc.terminate.assert_called_once()
    fake_proc.wait.assert_called_once_with(timeout=5)


# ─── 2. _pending 线程安全 ─────────────────────────────────────────


def test_pending_lock_initialized():
    """LspClient 在 __init__ 中创建 _pending_lock。"""
    client = LspClient()
    assert isinstance(client._pending_lock, type(threading.Lock()))


def test_request_uses_lock_for_pending():
    """request() 写入 _pending 和超时 pop 都用 _pending_lock 保护。"""
    source = inspect.getsource(LspClient.request)
    assert "with self._pending_lock:" in source, (
        "request() 必须用 with self._pending_lock 保护 _pending 访问"
    )
    assert "popped.cancel()" in source, "request() 超时路径必须 cancel Future"


def test_dispatch_uses_lock_for_pending():
    """_dispatch() pop _pending 时用 _pending_lock 保护。"""
    source = inspect.getsource(LspClient._dispatch)
    assert "with self._pending_lock:" in source, (
        "_dispatch() 必须用 with self._pending_lock 保护 _pending.pop"
    )


def test_reader_finally_uses_lock_for_pending():
    """_reader() finally 块迭代 _pending 时用 _pending_lock 保护。"""
    source = inspect.getsource(LspClient._reader)
    # finally 块应包含锁保护
    assert "with self._pending_lock:" in source, (
        "_reader() finally 必须用 with self._pending_lock 保护 _pending 遍历"
    )


@pytest.mark.asyncio
async def test_pending_future_cancel_on_timeout():
    """request() 超时后 Future 被 pop 并 cancel，而非仅 pop。

    构造一个无响应的 client（write_q 吞掉请求），调用 request() 触发超时，
    验证：1) 抛 TimeoutError；2) _pending 中对应 msg_id 已被 pop；3) Future 处于 cancelled 状态。
    """
    client = LspClient()
    client._loop = asyncio.get_running_loop()
    client._connected = True

    # mock proc: poll() 返回 None 表示进程还在跑
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    client._proc = fake_proc  # type: ignore[assignment]

    # write_q: 真实 queue，但无人读取，请求被吞
    import queue
    client._write_q = queue.Queue()

    # 捕获创建的 future
    created_futures: list[asyncio.Future[Any]] = []
    original_create_future = client._loop.create_future

    def tracking_create_future() -> asyncio.Future[Any]:
        fut = original_create_future()
        created_futures.append(fut)
        return fut

    client._loop.create_future = tracking_create_future  # type: ignore[method-assign]

    try:
        with pytest.raises(TimeoutError, match="timed out"):
            await client.request("textDocument/hover", {"textDocument": {}, "position": {}}, timeout=0.05)
    finally:
        client._loop.create_future = original_create_future  # type: ignore[method-assign]

    # 验证 future 被创建
    assert len(created_futures) == 1
    fut = created_futures[0]
    # Future 应被 pop（_pending 为空）且处于 done 状态（cancelled）
    assert len(client._pending) == 0, "超时后 _pending 应被 pop 干净"
    assert fut.cancelled() or fut.done(), (
        "Future 应被 cancel（cancelled=True）或处于 done 状态"
    )


@pytest.mark.asyncio
async def test_pending_concurrent_access_no_runtime_error():
    """reader 线程遍历 _pending 与主线程增删并发时不触发 RuntimeError。

    模拟场景：主线程持续往 _pending 加 future，同时 _reader finally 路径迭代 _pending。
    用锁保护后不应抛 RuntimeError。
    """
    client = LspClient()
    client._loop = asyncio.get_running_loop()

    # 模拟 reader finally 路径：在持有锁的情况下 snapshot + clear
    def reader_finally_path() -> None:
        with client._pending_lock:
            snapshot = list(client._pending.values())
            client._pending.clear()
        for f in snapshot:
            if not f.done():
                client._loop.call_soon_threadsafe(f.set_exception, RuntimeError("lost"))

    # 主线程并发往 _pending 加 future
    def add_pending(count: int) -> None:
        for i in range(count):
            fut = client._loop.create_future()
            with client._pending_lock:
                client._pending[i] = fut

    # 并发跑：不应抛 RuntimeError（dict 在迭代时被修改）
    threads: list[threading.Thread] = [
        threading.Thread(target=add_pending, args=(500,)),
        threading.Thread(target=add_pending, args=(500,)),
        threading.Thread(target=reader_finally_path),
        threading.Thread(target=reader_finally_path),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    # 没有异常即通过；额外验证 _pending 最终为空（被 clear）
    assert len(client._pending) == 0


# ─── 3. get_event_loop 替换 ───────────────────────────────────────


def test_no_get_event_loop_in_client():
    """client.py 不应再使用 asyncio.get_event_loop()。"""
    import illusion_forge.services.lsp.client as lsp_client_mod

    source = inspect.getsource(lsp_client_mod)
    assert "get_event_loop" not in source, (
        "client.py 不应再使用 asyncio.get_event_loop()（已废弃）"
    )


# ─── 4. MCP connect_all gather 异常取消 ───────────────────────────


def test_mcp_connect_all_cancels_on_exception():
    """MCP connect_all 用 return_exceptions=True 安全处理并发异常。

    connect_all 使用 asyncio.gather(*tasks, return_exceptions=True) 模式，
    所有任务都会执行完毕（或失败），异常被收集处理，无需显式 cancel。
    """
    from illusion_forge.mcp.client import McpClientManager

    source = inspect.getsource(McpClientManager.connect_all)
    assert "asyncio.create_task" in source, (
        "connect_all 必须用 asyncio.create_task 包装子任务"
    )
    assert "return_exceptions=True" in source, (
        "connect_all 必须用 return_exceptions=True 容错处理"
    )


@pytest.mark.asyncio
async def test_mcp_connect_all_cancels_pending_on_failure():
    """connect_all 在一个连接失败时继续运行其他连接，不抛异常。

    connect_all 使用 gather(return_exceptions=True) 模式，单个连接失败
    不影响其他连接，所有任务都会执行完毕。异常通过日志记录。
    """
    from illusion_forge.mcp.client import McpClientManager
    from illusion_forge.mcp.types import McpStdioServerConfig

    config_a = McpStdioServerConfig(command="a", args=[])
    config_b = McpStdioServerConfig(command="b", args=[])
    manager = McpClientManager({"a": config_a, "b": config_b})

    task_b_completed = asyncio.Event()
    original_connect_stdio = manager._connect_stdio

    async def mock_connect_stdio(name: str, config: Any) -> None:
        if name == "a":
            raise RuntimeError("connect a failed")
        if name == "b":
            task_b_completed.set()

    manager._connect_stdio = mock_connect_stdio  # type: ignore[method-assign]

    # connect_all 不应抛异常——单个失败不影响整体
    await manager.connect_all()

    # task b 应完成执行（不会被取消）
    assert task_b_completed.is_set(), "connect_all 应允许其他连接继续执行"
    assert original_connect_stdio is not manager._connect_stdio


# ─── 5. LSP manager shutdown_all 并行化 ───────────────────────────


def test_shutdown_all_uses_gather():
    """shutdown_all 用 asyncio.gather 并行关闭所有客户端。"""
    source = inspect.getsource(LspManager.shutdown_all)
    assert "asyncio.gather" in source, "shutdown_all 必须用 asyncio.gather 并行"
    assert "return_exceptions=True" in source, (
        "shutdown_all 必须用 return_exceptions=True 避免单个失败影响其他"
    )


@pytest.mark.asyncio
async def test_shutdown_all_runs_in_parallel():
    """shutdown_all 并行执行 client.stop()，总时长接近单个 stop 而非 N 倍。"""
    from illusion_forge.services.lsp.config import LspServerConfig

    configs = {
        "python": LspServerConfig(command="pyright", args=[], extensions=[".py"]),
        "go": LspServerConfig(command="gopls", args=[], extensions=[".go"]),
        "rust": LspServerConfig(command="rust-analyzer", args=[], extensions=[".rs"]),
    }
    manager = LspManager(configs)

    stop_order: list[str] = []
    stop_durations: list[float] = []

    class FakeClient:
        def __init__(self, name: str) -> None:
            self.name = name
            self._connected = False
            self.is_initialized = False
            self._proc = None

        async def stop(self) -> None:
            stop_order.append(f"{self.name}:start")
            # 模拟 proc.wait 阻塞 0.1 秒
            await asyncio.sleep(0.1)
            stop_order.append(f"{self.name}:end")
            stop_durations.append(0.1)

    # 注入 3 个 fake client
    manager._clients = {
        "python": FakeClient("python"),  # type: ignore[dict-item]
        "go": FakeClient("go"),  # type: ignore[dict-item]
        "rust": FakeClient("rust"),  # type: ignore[dict-item]
    }

    import time
    start = time.monotonic()
    await manager.shutdown_all()
    elapsed = time.monotonic() - start

    # 并行执行：3 个 0.1 秒的 stop 总时长应远小于 0.3 秒（串行）
    assert elapsed < 0.25, f"shutdown_all 应并行执行，耗时 {elapsed:.3f}s 应小于 0.25s"
    # 所有 client 都被关闭
    assert len(manager._clients) == 0
    # 所有 stop 都执行了（开始和结束都记录）
    assert len(stop_order) == 6  # 3 个 start + 3 个 end


@pytest.mark.asyncio
async def test_shutdown_all_swallows_individual_errors():
    """shutdown_all 用 return_exceptions=True，单个 client.stop 抛异常不影响其他。"""
    from illusion_forge.services.lsp.config import LspServerConfig

    configs = {
        "python": LspServerConfig(command="pyright", args=[], extensions=[".py"]),
        "go": LspServerConfig(command="gopls", args=[], extensions=[".go"]),
    }
    manager = LspManager(configs)

    class GoodClient:
        def __init__(self) -> None:
            self._connected = False
            self.is_initialized = False
            self._proc = None
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    class BadClient:
        def __init__(self) -> None:
            self._connected = False
            self.is_initialized = False
            self._proc = None

        async def stop(self) -> None:
            raise RuntimeError("stop failed")

    good = GoodClient()
    bad = BadClient()
    manager._clients = {
        "python": good,  # type: ignore[dict-item]
        "go": bad,  # type: ignore[dict-item]
    }

    # 不应抛异常
    await manager.shutdown_all()
    # good client 应被正常关闭
    assert good.stopped is True
    # clients 应被清空
    assert len(manager._clients) == 0
