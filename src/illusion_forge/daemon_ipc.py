# src/illusion_forge/daemon_ipc.py
"""守护进程 IPC 层
==================

跨平台的守护进程间通信（IPC）模块。

用 Named Pipe (Windows) / Unix Socket (Unix) 替代 PID 文件 + refs 文件，
从根本上消除 PID 复用和残留文件问题。

核心设计：
    - DaemonServer: 守护进程侧，创建 pipe/socket，accept 连接，跟踪连接数
    - DaemonClient: 主程序侧，connect 到 pipe/socket，持有连接作为引用
    - 连接数 = 引用计数：所有主程序退出 → 连接归零 → 守护进程退出
    - 健康检查：Client 发 ping，Server 回 pong（含 daemon_pid）
    - 指纹检查：Client register 时发送指纹，Server 对比后回 ok/restart_required

协议：JSON 行协议（每行一个 JSON 消息，以 \\n 分隔）
    Client → {"type":"register","pid":1234,"fingerprint":"abc123"}
    Server → {"type":"ok"} 或 {"type":"restart_required"}
    Client → {"type":"ping"}
    Server → {"type":"pong","daemon_pid":5678,"channels":{...}}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, TypeVar, cast

logger = logging.getLogger(__name__)

_IS_WINDOWS = os.name == "nt"

T = TypeVar("T")


class DaemonType(Enum):
    """守护进程类型"""

    CRON = "cron"
    CHANNEL = "channel"


class DaemonClientRef:
    """线程安全的 DaemonClient 引用容器

    用于异步连接场景：spawn 守护进程后立即返回，后台线程轮询连接。
    连接成功后调用 set() 持有 client；主程序退出时调用 close() 关闭连接。

    线程安全：内部用 threading.Lock 保护。
    """

    def __init__(self) -> None:
        self._client: DaemonClient | None = None
        import threading

        self._lock = threading.Lock()

    def set(self, client: DaemonClient) -> None:
        """设置 client（如果已有则关闭新的）"""
        with self._lock:
            if self._client is None:
                self._client = client
            else:
                # 已有 client（可能主程序多次调用），关闭多余的
                close_client(client)

    def close(self) -> None:
        """关闭 client（线程安全）"""
        with self._lock:
            if self._client is not None:
                close_client(self._client)
                self._client = None


# 默认 pipe/socket 名称
def _default_pipe_name(daemon_type: DaemonType) -> str:
    """获取默认的 pipe/socket 名称"""
    if _IS_WINDOWS:
        return f"\\\\.\\pipe\\illusion_{daemon_type.value}"
    else:
        from illusion_forge.config.paths import get_channels_data_dir, get_cron_dir

        if daemon_type == DaemonType.CRON:
            return str(get_cron_dir() / "cron_daemon.sock")
        else:
            return str(get_channels_data_dir() / "channel_daemon.sock")


def _get_channel_status_provider() -> Callable[[], dict[str, Any]] | None:
    """获取渠道状态提供器（延迟导入避免循环依赖）"""
    try:
        from illusion_forge.channels.serve import get_channel_status

        return get_channel_status
    except ImportError:
        return None


# ─── Windows Named Pipe 底层操作 ───

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.windll.kernel32

    # 64-bit Windows + 64-bit Python 下 ctypes.windll 函数默认返回 c_int（32 位），
    # 会截断 CreateNamedPipeW / CreateFileW 返回的 64 位 HANDLE 值。
    # 必须显式设置 restype，避免句柄被截断。
    _kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.ConnectNamedPipe.restype = wintypes.BOOL
    _kernel32.ReadFile.restype = wintypes.BOOL
    _kernel32.WriteFile.restype = wintypes.BOOL
    _kernel32.GetLastError.restype = wintypes.DWORD

    # Win32 常量
    _PIPE_ACCESS_DUPLEX = 0x00000003
    _PIPE_TYPE_BYTE = 0x00000000
    # PIPE_WAIT = 0x00000000：阻塞模式是默认行为，不是 flag 位。
    # （brief 误用 0x00000080，会令 dwPipeMode 出现未定义位 → ERROR_INVALID_PARAMETER 87）
    _PIPE_WAIT = 0x00000000
    _PIPE_UNLIMITED_INSTANCES = 255
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _OPEN_EXISTING = 3
    _ERROR_PIPE_CONNECTED = 535
    _ERROR_PIPE_NOT_CONNECTED = 233

    def _win_create_pipe(name: str) -> int:
        """创建 Named Pipe 实例（服务端）"""
        handle: int = _kernel32.CreateNamedPipeW(
            name,
            _PIPE_ACCESS_DUPLEX,
            _PIPE_TYPE_BYTE | _PIPE_WAIT,
            _PIPE_UNLIMITED_INSTANCES,
            65536,
            65536,
            0,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE or handle == 0:
            err = _kernel32.GetLastError()
            raise OSError(f"CreateNamedPipe failed: error={err}")
        return handle

    def _win_connect_pipe(handle: int) -> bool:
        """等待客户端连接（阻塞）"""
        result = _kernel32.ConnectNamedPipe(handle, None)
        if result != 0:
            return True
        # ConnectNamedPipe 返回 0 时，ERROR_PIPE_CONNECTED 表示客户端已连接
        return bool(_kernel32.GetLastError() == _ERROR_PIPE_CONNECTED)

    def _win_read_pipe(handle: int, size: int = 65536) -> bytes:
        """从 pipe 读取数据（阻塞）"""
        buf = ctypes.create_string_buffer(size)
        bytes_read = wintypes.DWORD()
        success = _kernel32.ReadFile(handle, buf, size, ctypes.byref(bytes_read), None)
        if success == 0:
            err = _kernel32.GetLastError()
            raise OSError(f"ReadFile failed: error={err}")
        return buf.raw[: bytes_read.value]

    def _win_write_pipe(handle: int, data: bytes) -> int:
        """写入 pipe（阻塞）"""
        bytes_written = wintypes.DWORD()
        success = _kernel32.WriteFile(handle, data, len(data), ctypes.byref(bytes_written), None)
        if success == 0:
            err = _kernel32.GetLastError()
            raise OSError(f"WriteFile failed: error={err}")
        return bytes_written.value

    def _win_connect_to_pipe(name: str) -> int | None:
        """客户端连接到 Named Pipe，失败返回 None"""
        handle: int = _kernel32.CreateFileW(
            name,
            _GENERIC_READ | _GENERIC_WRITE,
            0,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE or handle == 0:
            err = _kernel32.GetLastError()
            logger.debug("连接 Named Pipe 失败: %s, error=%d", name, err)
            return None
        return handle

    def _win_close_handle(handle: int) -> None:
        """关闭句柄"""
        _kernel32.CloseHandle(handle)

    def _win_cancel_io(handle: int) -> None:
        """取消句柄上所有未完成的 I/O 操作（用于解除 ReadFile/ConnectNamedPipe 阻塞）

        必须在 CloseHandle 之前调用：单独 CloseHandle 在有 pending I/O 时会阻塞。
        """
        _kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        _kernel32.CancelIoEx.restype = wintypes.BOOL
        _kernel32.CancelIoEx(handle, None)


# ─── 连接抽象 ───


class _BaseConnection:
    """连接抽象基类"""

    async def read_line(self, timeout: float | None = None) -> str | None:
        """读取一行 JSON，连接关闭返回 None

        Args:
            timeout: 超时秒数，None 表示无限等待
        """
        raise NotImplementedError

    async def write_line(self, line: str) -> None:
        """写入一行 JSON"""
        raise NotImplementedError

    async def close(self) -> None:
        """关闭连接"""
        raise NotImplementedError


if _IS_WINDOWS:

    class _WindowsPipeConnection(_BaseConnection):
        """Windows Named Pipe 连接，支持超时取消读取。

        通过专用 executor 提交读取线程，线程内 call_soon_threadsafe 桥接结果。
        超时后 CloseHandle 强制解除 ReadFile 阻塞，避免线程泄漏。

        Attributes:
            _read_executor: 专用线程池（max_workers=1），避免占用默认线程池
            _handle: pipe 句柄
            _read_buf: 读取缓冲区，累积部分数据直到遇到换行符
            _closed: 连接是否已关闭
        """

        def __init__(self, handle: int) -> None:
            self._read_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="daemon-pipe"
            )
            self._handle: int | None = handle
            self._read_buf = b""
            self._closed = False

        async def read_line(self, timeout: float | None = None) -> str | None:
            """读取一行（以 \\n 结尾），连接关闭返回 None。

            Args:
                timeout: 超时秒数，None 表示无限等待

            Returns:
                读取到的行（不含换行符），连接关闭时返回 None

            Raises:
                asyncio.TimeoutError: 超时后抛出，同时 CloseHandle 解除线程阻塞
            """
            while b"\n" not in self._read_buf:
                if self._closed:
                    return None
                if self._handle is None:
                    return None

                loop = asyncio.get_running_loop()
                future: asyncio.Future[bytes] = asyncio.Future()
                handle = self._handle

                def _set_result(fut: asyncio.Future[bytes], data: bytes) -> None:
                    """安全设置 future 结果（避免对已取消 future 抛 InvalidStateError）"""
                    if not fut.done():
                        fut.set_result(data)

                def _set_exception(fut: asyncio.Future[bytes], exc: BaseException) -> None:
                    """安全设置 future 异常（避免对已取消 future 抛 InvalidStateError）"""
                    if not fut.done():
                        fut.set_exception(exc)

                def _read_thread(
                    handle: int = handle,
                    loop: asyncio.AbstractEventLoop = loop,
                    future: asyncio.Future[bytes] = future,
                ) -> None:
                    """读取线程：阻塞读 pipe，通过 call_soon_threadsafe 桥接结果。"""
                    try:
                        data = _win_read_pipe(handle, 4096)
                        loop.call_soon_threadsafe(_set_result, future, data)
                    except OSError as exc:
                        loop.call_soon_threadsafe(_set_exception, future, exc)

                self._read_executor.submit(_read_thread)

                try:
                    chunk = await asyncio.wait_for(future, timeout=timeout)
                except TimeoutError:
                    # 超时后强制关闭 handle，解除 ReadFile 阻塞
                    # 必须先 CancelIoEx 取消 pending ReadFile，否则 CloseHandle 会阻塞
                    self._closed = True
                    try:
                        _win_cancel_io(handle)
                        _win_close_handle(handle)
                    except OSError as exc:
                        logger.debug("超时关闭 pipe 句柄失败: %s", exc)
                    self._handle = None
                    raise
                except OSError:
                    self._closed = True
                    return None

                if not chunk:
                    self._closed = True
                    return None
                self._read_buf += chunk

            idx = self._read_buf.index(b"\n")
            line = self._read_buf[:idx]
            self._read_buf = self._read_buf[idx + 1 :]
            return line.decode("utf-8")

        async def write_line(self, line: str) -> None:
            """写入一行"""
            data = (line + "\n").encode("utf-8")
            if self._handle is None:
                self._closed = True
                raise OSError("pipe handle is closed")
            try:
                await asyncio.to_thread(_win_write_pipe, self._handle, data)
            except OSError:
                self._closed = True
                raise

        async def close(self) -> None:
            """关闭连接和 executor"""
            if not self._closed:
                self._closed = True
                if self._handle is not None:
                    try:
                        # CancelIoEx + CloseHandle：避免 pending I/O 时 CloseHandle 阻塞
                        _win_cancel_io(self._handle)
                        _win_close_handle(self._handle)
                    except OSError as exc:
                        logger.debug("关闭 pipe 句柄失败: %s", exc)
                    self._handle = None
            # 关闭专用 executor，释放线程资源
            self._read_executor.shutdown(wait=False, cancel_futures=True)

else:

    class _UnixSocketConnection(_BaseConnection):
        """Unix Socket 连接"""

        def __init__(
            self,
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            self._reader = reader
            self._writer = writer
            self._closed = False

        async def read_line(self, timeout: float | None = None) -> str | None:
            """读取一行，连接关闭返回 None

            Args:
                timeout: 超时秒数，None 表示无限等待
            """
            try:
                if timeout is not None:
                    data = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
                else:
                    data = await self._reader.readline()
            except (TimeoutError, ConnectionResetError, asyncio.IncompleteReadError):
                self._closed = True
                return None
            if not data:
                self._closed = True
                return None
            return data.decode("utf-8").strip()

        async def write_line(self, line: str) -> None:
            """写入一行"""
            if self._closed:
                raise OSError("Unix socket 连接已关闭")
            try:
                self._writer.write((line + "\n").encode("utf-8"))
                await self._writer.drain()
            except OSError:
                self._closed = True
                raise

        async def close(self) -> None:
            """关闭连接

            注意：即使 read_line 已检测到对端 EOF（_closed=True），本地 transport
            仍必须显式 close——否则 transport 不会触发 connection_lost，
            Python 3.12 的 Server.wait_closed() 会因 active_count 不归零永久挂起
            （server.stop() 挂死，CI Ubuntu 曾因此超时）。
            writer.close() 幂等，重复调用安全。
            """
            self._closed = True
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError as exc:
                logger.debug("关闭 Unix socket 连接失败: %s", exc)


# ─── DaemonServer ───


class DaemonServer:
    """守护进程 IPC 服务端

    创建 pipe/socket 并 accept 连接，跟踪活跃连接数。
    连接数归零时可通过 wait_for_no_connections 触发守护进程退出。

    Attributes:
        daemon_type: 守护进程类型
        daemon_pid: 守护进程 PID（用于 pong 响应）
        pipe_name: pipe/socket 名称
        fingerprint: 配置指纹（仅渠道守护进程需要，None 表示不检查）
    """

    def __init__(
        self,
        daemon_type: DaemonType,
        daemon_pid: int,
        pipe_name: str | None = None,
        fingerprint: str | None = None,
        on_reload: Callable[[], None] | None = None,
        on_start_channel: Callable[[str], None] | None = None,
        on_stop_channel: Callable[[str], None] | None = None,
        on_cron_claim: Callable[[], Any] | None = None,
        on_cron_report: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self._daemon_type = daemon_type
        self._daemon_pid = daemon_pid
        self._pipe_name = pipe_name or _default_pipe_name(daemon_type)
        self._fingerprint = fingerprint
        self._on_reload = on_reload
        # 渠道 runner 动态启停回调（由 serve.py 注入，在 IPC 线程调用，
        # 回调内部用 loop.call_soon_threadsafe 调度到守护进程事件循环）
        self._on_start_channel = on_start_channel
        self._on_stop_channel = on_stop_channel
        # cron 委托执行回调（由 cron_serve.py 注入）：主程序领取待委托任务 /
        # 上报执行结果。与渠道回调一样在 IPC 协程内调用（同事件循环单线程，
        # cron_delegation 的队列操作无需加锁）。
        self._on_cron_claim = on_cron_claim
        self._on_cron_report = on_cron_report
        self._connections: set[_BaseConnection] = set()
        self._client_tasks: set[asyncio.Task[None]] = set()
        self._stop = False
        # 是否曾有客户端连接过（防止启动竞态：守护进程刚启动时还没有客户端连接，
        # wait_for_no_connections 不应在此时判定"连接归零"而退出）
        self._had_connection = False
        self._accept_task: asyncio.Task[None] | None = None
        self._unix_server: asyncio.Server | None = None
        # Windows: 预创建的 pipe 句柄（由 accept loop 消费）
        self._pending_pipe_handle: int | None = None
        # Windows: accept loop 当前正在使用的 pipe 句柄（用于 stop() 时强制关闭解除阻塞）
        self._active_pipe_handle: int | None = None

    @property
    def connection_count(self) -> int:
        """当前活跃连接数"""
        return len(self._connections)

    async def start(self) -> None:
        """启动服务端，开始 accept 连接"""
        if _IS_WINDOWS:
            # 预创建首个 pipe 实例（同步），避免 client 在 accept loop 创建 pipe 前连接
            # 导致 ERROR_FILE_NOT_FOUND 的竞态。
            first_handle = await asyncio.to_thread(_win_create_pipe, self._pipe_name)
            self._pending_pipe_handle = first_handle
            self._accept_task = asyncio.create_task(self._windows_accept_loop())
        elif sys.platform != "win32":
            # Unix: 先清理残留 socket 文件
            try:
                os.unlink(self._pipe_name)
            except FileNotFoundError:
                pass
            self._unix_server = await asyncio.start_unix_server(
                self._handle_unix_client, path=self._pipe_name
            )
            # 设置 socket 文件权限为 0600（仅属主可读写）
            try:
                os.chmod(self._pipe_name, 0o600)
            except OSError:
                pass
            logger.debug("DaemonServer 监听: %s", self._pipe_name)

    async def stop(self) -> None:
        """停止服务端，关闭所有连接"""
        self._stop = True
        if _IS_WINDOWS:
            # 关闭预创建但未被消费的 pipe 句柄
            # （此句柄尚未传入 ConnectNamedPipe，CloseHandle 安全）
            if self._pending_pipe_handle is not None:
                _win_close_handle(self._pending_pipe_handle)
                self._pending_pipe_handle = None
            # 用 CancelIoEx + CloseHandle 替代循环连接唤醒 accept loop
            # CancelIoEx 取消 ConnectNamedPipe，CloseHandle 关闭句柄
            if self._active_pipe_handle is not None:
                try:
                    _win_cancel_io(self._active_pipe_handle)
                    _win_close_handle(self._active_pipe_handle)
                except OSError as exc:
                    logger.debug("停止服务端时关闭活跃 pipe 句柄失败: %s", exc)
                self._active_pipe_handle = None
            # 保留单次连接作为兜底（handle 可能刚好在两次迭代之间）
            if self._accept_task is not None and not self._accept_task.done():
                try:
                    fake_handle = await asyncio.to_thread(_win_connect_to_pipe, self._pipe_name)
                    if fake_handle is not None:
                        _win_close_handle(fake_handle)
                except OSError as exc:
                    logger.debug("唤醒 accept loop 失败: %s", exc)
        if self._accept_task:
            self._accept_task.cancel()
            try:
                await self._accept_task
            except asyncio.CancelledError:
                pass
        # 先主动关闭所有活跃连接：唤醒阻塞在 read_line 上的 handler 协程
        # （transport 关闭 → readline EOF → handler 退出 → connection_lost →
        #  Server 的 active_count 归零），再 wait_closed() 等待完成。
        # 顺序不可颠倒：若先 wait_closed()，handler 阻塞在无限 read_line 上
        # 永不退出，wait_closed() 永久挂起。
        for conn in list(self._connections):
            await conn.close()
        self._connections.clear()
        if self._unix_server:
            self._unix_server.close()
            await self._unix_server.wait_closed()

    async def _windows_accept_loop(self) -> None:
        """Windows Named Pipe accept 循环"""
        while not self._stop:
            # 优先消费 start() 预创建的 pipe 句柄（避免竞态）
            if self._pending_pipe_handle is not None:
                handle = self._pending_pipe_handle
                self._pending_pipe_handle = None
            else:
                try:
                    handle = await asyncio.to_thread(_win_create_pipe, self._pipe_name)
                except OSError as exc:
                    logger.error("创建 Named Pipe 失败: %s", exc)
                    await asyncio.sleep(1)
                    continue
            # 等待客户端连接（阻塞，在线程中执行）
            # stop() 会通过 CloseHandle 强制解除 ConnectNamedPipe 阻塞
            self._active_pipe_handle = handle
            try:
                connected = await asyncio.to_thread(_win_connect_pipe, handle)
            except asyncio.CancelledError:
                _win_close_handle(handle)
                self._active_pipe_handle = None
                raise
            except OSError as exc:
                logger.warning("accept 连接异常: %s", exc)
                _win_close_handle(handle)
                self._active_pipe_handle = None
                continue
            self._active_pipe_handle = None
            if connected and not self._stop:
                conn = _WindowsPipeConnection(handle)
                self._connections.add(conn)
                self._had_connection = True
                task = asyncio.create_task(self._handle_client(conn))
                self._client_tasks.add(task)
                task.add_done_callback(self._client_tasks.discard)
            else:
                # 未连接或已停止：关闭句柄
                _win_close_handle(handle)

    async def _handle_unix_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Unix Socket 客户端处理"""
        conn = _UnixSocketConnection(reader, writer)
        self._connections.add(conn)
        self._had_connection = True
        await self._handle_client(conn)

    async def _handle_client(self, conn: _BaseConnection) -> None:
        """处理客户端连接：读取消息，响应 ping/register"""
        try:
            while not self._stop:
                # 无限等待读取。不用 wait_for 包裹：超时取消 read_line 会与
                # 下一轮读取产生 StreamReader._waiter 竞态（旧协程取消的 finally
                # 清掉新协程的 waiter，导致后续数据无人唤醒），曾造成 ping
                # 约 50% 无响应。阻塞由 stop() 先关闭连接唤醒（EOF → 返回 None）。
                line = await conn.read_line()
                if line is None:
                    break  # 客户端断开
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                resp = self._handle_message(msg)
                if resp is not None:
                    try:
                        await conn.write_line(json.dumps(resp))
                    except OSError:
                        break  # 写入失败，客户端已断开
        finally:
            self._connections.discard(conn)
            await conn.close()

    def _handle_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """处理消息，返回响应"""
        msg_type = msg.get("type")
        if msg_type == "ping":
            return {
                "type": "pong",
                "daemon_pid": self._daemon_pid,
                "connections": self.connection_count,
                "channels": self._get_channel_status(),
            }
        elif msg_type == "register":
            # 指纹检查（仅渠道守护进程）
            if self._fingerprint is not None:
                client_fp = msg.get("fingerprint")
                if client_fp != self._fingerprint:
                    return {"type": "restart_required"}
            return {"type": "ok"}
        elif msg_type == "reload":
            # 通知守护进程重新加载配置（如主程序 /model 切换模型后）
            if self._on_reload is not None:
                try:
                    self._on_reload()
                except (AttributeError, TypeError, RuntimeError) as exc:
                    logger.warning("reload 回调异常: %s", exc)
                    return {"type": "error", "message": str(exc)}
            return {"type": "ok"}
        elif msg_type == "start_channel":
            # 启动指定渠道 runner（回调内部调度到守护进程事件循环）
            name = str(msg.get("name", ""))
            if self._on_start_channel is not None:
                try:
                    self._on_start_channel(name)
                except (AttributeError, TypeError, RuntimeError) as exc:
                    logger.warning("start_channel 回调异常: %s", exc)
                    return {"type": "error", "message": str(exc)}
            return {"type": "ok"}
        elif msg_type == "stop_channel":
            # 停止指定渠道 runner（回调内部调度到守护进程事件循环）
            name = str(msg.get("name", ""))
            if self._on_stop_channel is not None:
                try:
                    self._on_stop_channel(name)
                except (AttributeError, TypeError, RuntimeError) as exc:
                    logger.warning("stop_channel 回调异常: %s", exc)
                    return {"type": "error", "message": str(exc)}
            return {"type": "ok"}
        elif msg_type == "cron_claim_pending":
            # 主程序领取待委托的 cron 任务（指定会话执行）
            job: Any = None
            if self._on_cron_claim is not None:
                try:
                    job = self._on_cron_claim()
                except (AttributeError, TypeError, RuntimeError) as exc:
                    logger.warning("cron_claim_pending 回调异常: %s", exc)
                    return {"type": "error", "message": str(exc)}
            return {"type": "ok", "job": job}
        elif msg_type == "cron_report_result":
            # 主程序上报 cron 委托任务执行结果
            job_id = str(msg.get("job_id", ""))
            result = msg.get("result")
            if self._on_cron_report is not None and isinstance(result, dict):
                try:
                    self._on_cron_report(job_id, result)
                except (AttributeError, TypeError, RuntimeError) as exc:
                    logger.warning("cron_report_result 回调异常: %s", exc)
                    return {"type": "error", "message": str(exc)}
            return {"type": "ok"}
        return None

    def _get_channel_status(self) -> dict[str, Any]:
        """获取渠道状态（用于 pong 响应）"""
        provider = _get_channel_status_provider()
        if provider is not None:
            try:
                return provider()
            except (AttributeError, KeyError, TypeError, ValueError, RuntimeError) as exc:
                logger.debug("获取渠道状态失败: %s", exc)
        return {}

    async def wait_for_no_connections(self, grace_seconds: float = 3.0) -> None:
        """等待所有连接断开

        连接归零后等 grace_seconds 宽限期，仍为空则返回。
        用于守护进程判断是否该退出。

        注意：守护进程刚启动时还没有客户端连接，不能立即判定"连接归零"。
        先等待首个客户端连接（_had_connection），再进入连接归零检查。
        """
        # 阶段 1：等待首个客户端连接（无超时，防止启动竞态）
        while not self._stop and not self._had_connection:
            await asyncio.sleep(0.5)
        # 阶段 2：等待所有连接断开（带宽限期）
        while not self._stop:
            if self.connection_count == 0:
                # 宽限期：等 grace_seconds 后再次检查
                await asyncio.sleep(grace_seconds)
                if self.connection_count == 0:
                    return
            else:
                await asyncio.sleep(0.5)


# ─── DaemonClient ───


class DaemonClient:
    """守护进程 IPC 客户端

    连接到 DaemonServer，持有连接作为引用计数。
    进程退出时 OS 自动关闭连接，守护进程检测到后退出。

    Attributes:
        daemon_type: 守护进程类型
        pid: 主程序 PID
        fingerprint: 配置指纹（仅渠道守护进程需要）
    """

    def __init__(
        self,
        daemon_type: DaemonType,
        pid: int,
        fingerprint: str | None = None,
        pipe_name: str | None = None,
    ) -> None:
        self._daemon_type = daemon_type
        self._pid = pid
        self._fingerprint = fingerprint
        self._pipe_name = pipe_name or _default_pipe_name(daemon_type)
        self._conn: _BaseConnection | None = None
        self._daemon_pid: int | None = None

    @property
    def daemon_pid(self) -> int | None:
        """守护进程 PID（从 pong 响应获取）"""
        return self._daemon_pid

    @property
    def is_connected(self) -> bool:
        """是否已连接（检查底层连接是否已关闭）"""
        if self._conn is None:
            return False
        # 检查底层连接的 _closed 标志（read_line 超时或 write_line 失败后置 True）
        return not getattr(self._conn, "_closed", False)

    async def connect(self) -> bool:
        """连接到守护进程

        Returns:
            bool: 连接成功返回 True，守护进程未运行返回 False
        """
        if _IS_WINDOWS:
            return await self._windows_connect()
        else:
            return await self._unix_connect()

    async def _windows_connect(self) -> bool:
        """Windows Named Pipe 连接"""
        try:
            handle = await asyncio.to_thread(_win_connect_to_pipe, self._pipe_name)
        except OSError:
            return False
        if handle is None:
            return False
        self._conn = _WindowsPipeConnection(handle)
        # 让 server accept loop 有时间处理连接：
        # CreateFileW 连接后，server 端 ConnectNamedPipe（在线程中）才返回，
        # 需等待事件循环调度回调将连接加入 self._connections。
        await asyncio.sleep(0.05)
        return True

    async def _unix_connect(self) -> bool:
        """Unix Socket 连接（仅 Unix 平台可用）"""
        if sys.platform == "win32":
            return False
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._pipe_name),
                timeout=5.0,
            )
        except (TimeoutError, FileNotFoundError, ConnectionRefusedError):
            return False
        self._conn = _UnixSocketConnection(reader, writer)
        # 让 server accept loop 有时间处理连接：
        # asyncio.open_unix_connection 成功后，server 端 _handle_unix_client 才被调度，
        # 需等待事件循环调度回调将连接加入 self._connections。
        await asyncio.sleep(0.05)
        return True

    async def register(self) -> dict[str, Any]:
        """发送 register 消息，获取响应

        Returns:
            dict: {"type":"ok"} 或 {"type":"restart_required"}
        """
        if self._conn is None:
            raise RuntimeError("未连接")
        msg: dict[str, Any] = {"type": "register", "pid": self._pid}
        if self._fingerprint is not None:
            msg["fingerprint"] = self._fingerprint
        await self._conn.write_line(json.dumps(msg))
        line = await self._conn.read_line(timeout=5.0)
        if line is None:
            raise ConnectionError("连接关闭")
        result: dict[str, Any] = json.loads(line)
        if result.get("daemon_pid"):
            self._daemon_pid = result["daemon_pid"]
        return result

    async def ping(self, timeout: float = 10.0) -> dict[str, Any] | None:
        """发送 ping，等待 pong

        Args:
            timeout: 超时秒数

        Returns:
            dict: pong 响应，超时返回 None
        """
        if self._conn is None:
            return None
        try:
            await self._conn.write_line(json.dumps({"type": "ping"}))
            line = await self._conn.read_line(timeout=timeout)
        except (TimeoutError, OSError):
            return None
        if line is None:
            return None
        try:
            resp: dict[str, Any] = json.loads(line)
            if resp.get("type") == "pong":
                self._daemon_pid = resp.get("daemon_pid")
            return resp
        except json.JSONDecodeError:
            return None

    async def reload(self, timeout: float = 5.0) -> dict[str, Any] | None:
        """发送 reload 消息，通知守护进程重新加载配置

        用于主程序 /model 切换模型后通知守护进程刷新 settings.json。

        Args:
            timeout: 超时秒数

        Returns:
            dict: 响应字典（{"type":"ok"} 或 {"type":"error",...}），失败返回 None
        """
        if self._conn is None:
            return None
        try:
            await self._conn.write_line(json.dumps({"type": "reload"}))
            line = await self._conn.read_line(timeout=timeout)
        except (TimeoutError, OSError):
            return None
        if line is None:
            return None
        try:
            result: dict[str, Any] = json.loads(line)
            return result
        except json.JSONDecodeError:
            return None

    async def start_channel(self, name: str, timeout: float = 5.0) -> dict[str, Any] | None:
        """发送 start_channel 消息，启动指定渠道 runner

        Args:
            name: 渠道名（feishu/weixin/qq）
            timeout: 超时秒数

        Returns:
            dict: 响应字典，失败返回 None
        """
        if self._conn is None:
            return None
        try:
            await self._conn.write_line(json.dumps({"type": "start_channel", "name": name}))
            line = await self._conn.read_line(timeout=timeout)
        except (TimeoutError, OSError):
            return None
        if line is None:
            return None
        try:
            return cast(dict[str, Any], json.loads(line))
        except json.JSONDecodeError:
            return None

    async def stop_channel(self, name: str, timeout: float = 5.0) -> dict[str, Any] | None:
        """发送 stop_channel 消息，停止指定渠道 runner

        Args:
            name: 渠道名（feishu/weixin/qq）
            timeout: 超时秒数

        Returns:
            dict: 响应字典，失败返回 None
        """
        if self._conn is None:
            return None
        try:
            await self._conn.write_line(json.dumps({"type": "stop_channel", "name": name}))
            line = await self._conn.read_line(timeout=timeout)
        except (TimeoutError, OSError):
            return None
        if line is None:
            return None
        try:
            return cast(dict[str, Any], json.loads(line))
        except json.JSONDecodeError:
            return None

    async def cron_claim_pending(self, timeout: float = 10.0) -> dict[str, Any] | None:
        """领取一个待委托的 cron 任务（指定会话执行）。

        轮询拉取模式：Web 主程序周期性调用，领取 cron 守护进程
        队列中待执行的指定会话任务。无任务时返回 None。

        Args:
            timeout: 超时秒数

        Returns:
            dict | None: 任务字典（含 id/session_id/prompt 等），无任务或失败返回 None
        """
        if self._conn is None:
            return None
        try:
            await self._conn.write_line(json.dumps({"type": "cron_claim_pending"}))
            line = await self._conn.read_line(timeout=timeout)
        except (TimeoutError, OSError):
            return None
        if line is None:
            return None
        try:
            resp = cast(dict[str, Any], json.loads(line))
        except json.JSONDecodeError:
            return None
        job = resp.get("job")
        return job if isinstance(job, dict) else None

    async def cron_report_result(
        self,
        job_id: str,
        result: dict[str, Any],
        timeout: float = 10.0,
    ) -> bool:
        """上报 cron 委托任务执行结果。

        Args:
            job_id: 任务 ID
            result: 执行结果字典（status/returncode/stdout/stderr 等）
            timeout: 超时秒数

        Returns:
            bool: 上报成功返回 True
        """
        if self._conn is None:
            return False
        try:
            await self._conn.write_line(json.dumps({
                "type": "cron_report_result",
                "job_id": job_id,
                "result": result,
            }))
            line = await self._conn.read_line(timeout=timeout)
        except (TimeoutError, OSError):
            return False
        if line is None:
            return False
        try:
            resp = cast(dict[str, Any], json.loads(line))
            return resp.get("type") == "ok"
        except json.JSONDecodeError:
            return False

    async def close(self) -> None:
        """关闭连接"""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


# ─── 同步辅助函数 ───
# 以下函数封装了 DaemonClient 的异步操作，在同一个事件循环中完成，
# 避免 Unix 上 StreamWriter 绑定到已关闭的 loop 导致 drain() 失败。
# 当检测到已有 running loop（如被 async 测试或 agent 调用）时，
# 在独立线程中运行协程，避免 "Cannot run the event loop while another
# loop is running" RuntimeError。


def _run_coro_sync(coro: Awaitable[T]) -> T:
    """同步运行协程到完成，兼容 sync 和 async 调用上下文

    - 无 running loop：创建新 loop 并 run_until_complete（原有行为）
    - 有 running loop：在独立线程中 asyncio.run，避免嵌套 loop

    Args:
        coro: 待运行的协程

    Returns:
        协程的返回值
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    # 已有 running loop：在新线程中运行，避免嵌套 loop
    def _runner() -> T:
        return asyncio.run(coro)  # type: ignore[arg-type]

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(_runner).result()


def connect_and_register(client: DaemonClient) -> tuple[bool, dict[str, Any] | None]:
    """在同一个事件循环中完成 connect + register

    Args:
        client: DaemonClient 实例

    Returns:
        tuple: (是否连接成功, register 响应)
        - 连接失败: (False, None)
        - 连接成功但 register 异常: (True, {"type": "ok"})
        - 连接成功且 register 成功: (True, 响应字典)
    """

    async def _do() -> tuple[bool, dict[str, Any] | None]:
        connected = await client.connect()
        if not connected:
            return False, None
        try:
            resp = await client.register()
        except (OSError, json.JSONDecodeError, RuntimeError):
            resp = {"type": "ok"}
        return True, resp

    return _run_coro_sync(_do())


def close_client(client: DaemonClient) -> None:
    """在独立事件循环中关闭 IPC 连接

    Args:
        client: DaemonClient 实例
    """

    async def _do() -> None:
        await client.close()

    try:
        _run_coro_sync(_do())
    except OSError as exc:
        logger.debug("关闭 IPC 连接失败: %s", exc)


def ping_daemon(client: DaemonClient, timeout: float = 2.0) -> dict[str, Any] | None:
    """在独立事件循环中 ping 守护进程

    Args:
        client: DaemonClient 实例
        timeout: 超时秒数

    Returns:
        dict: pong 响应，失败返回 None
    """

    async def _do() -> dict[str, Any] | None:
        connected = await client.connect()
        if not connected:
            return None
        try:
            return await client.ping(timeout=timeout)
        finally:
            await client.close()

    return _run_coro_sync(_do())


def notify_channel_daemon_reload() -> bool:
    """通知渠道守护进程重新加载 settings.json

    创建临时 DaemonClient，连接守护进程并发送 reload 消息。
    用于主程序 /model 命令切换模型后通知守护进程刷新配置。
    守护进程未运行时静默返回 False（无需 reload）。

    Returns:
        bool: 通知成功返回 True，守护进程未运行或通知失败返回 False
    """

    async def _do() -> bool:
        client = DaemonClient(
            daemon_type=DaemonType.CHANNEL,
            pid=os.getpid(),
        )
        connected = await client.connect()
        if not connected:
            return False
        try:
            resp = await client.reload()
            return resp is not None and resp.get("type") == "ok"
        finally:
            await client.close()

    try:
        return _run_coro_sync(_do())
    except (OSError, RuntimeError):
        return False
