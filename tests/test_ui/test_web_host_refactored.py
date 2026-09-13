"""WebBackendHost 重构测试。

覆盖 Task 7 的写路径 + 优雅关闭：
    - _emit 入队事件，不直接写 WebSocket
    - _write_loop 串行消费 _write_queue，WebSocket 断开时退出
    - _create_background_task 保留强引用
    - _resolve_pending_futures 在 shutdown 时 resolve 所有 pending future
    - _shutdown 优雅关闭序列（含写队列排空）
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from illusion_forge.ui.protocol import BackendEvent
from illusion_forge.ui.web.ws_host import WebBackendHost
from illusion_forge.utils.aioqueue import Queue, QueueShutDown


class _FakeWebSocket:
    """模拟 FastAPI WebSocket，仅实现 send_text 用于测试。"""

    def __init__(self, *, raise_on_send: bool = False) -> None:
        self.sent: list[str] = []
        self.raise_on_send = raise_on_send

    async def send_text(self, data: str) -> None:
        if self.raise_on_send:
            raise ConnectionError("WebSocket closed")
        self.sent.append(data)


def _make_host(**fields: Any) -> WebBackendHost:
    """绕过 __init__ 构造 host，仅设置测试所需字段。

    WebBackendHost.__init__ 需要 WebHostConfig 和 WebSocket 依赖，
    集成测试只验证 _shutdown / _emit / _write_loop 等方法行为，因此用
    object.__new__ 绕过构造，再手动注入字段。
    """
    host = object.__new__(WebBackendHost)
    # 默认字段集合（覆盖 _shutdown / _emit / _write_loop 等访问的全部属性）
    defaults: dict[str, Any] = {
        "_config": None,
        "_websocket": _FakeWebSocket(),
        "_bundle": None,
        "_sessions": {},
        "_active_session_id": None,
        "_write_queue": Queue(),
        "_write_task": None,
        "_dispatch_tasks": set(),
        "_request_queue": asyncio.Queue(),
        "_permission_requests": {},
        "_question_requests": {},
        "_session_allowed_tools": set(),
        "_running": True,
        "_ws_closed": False,
        "_periodic_task": None,
        "_cron_poll_task": None,
    }
    defaults.update(fields)
    for key, value in defaults.items():
        setattr(host, key, value)
    return host


# === 写路径测试 ===


def test_web_host_uses_write_queue():
    """WebBackendHost 使用 _write_queue 而非 _write_lock。"""
    host = _make_host()

    asyncio.run(host._emit(BackendEvent(type="shutdown")))

    assert host._write_queue.qsize() == 1
    event = host._write_queue.get_nowait()
    assert event.type == "shutdown"
    # 确认 _write_lock 已移除
    assert not hasattr(host, "_write_lock")


def test_write_loop_consumes_queue():
    """_write_loop 串行消费 _write_queue，shutdown 后退出。"""

    async def run() -> None:
        ws = _FakeWebSocket()
        host = _make_host(_websocket=ws)
        # 入队两个事件
        await host._emit(BackendEvent(type="shutdown"))
        await host._emit(BackendEvent(type="error", message="test"))
        # 启动写循环
        host._write_task = asyncio.create_task(host._write_loop())
        # 让写循环消费
        await asyncio.sleep(0.05)
        # shutdown 队列唤醒 _write_loop 退出
        host._write_queue.shutdown()
        await host._write_task
        # 队列应已排空，两个事件都已发送
        assert len(ws.sent) == 2

    asyncio.run(run())


def test_write_loop_survives_send_error():
    """_write_loop 在 WebSocket 写入失败时不退出，继续处理后续事件。

    原 break 行为会导致瞬态写入错误后所有后续事件（modal_request modal=None、
    task_stopped、line_complete 等）永久丢失，引发权限模态框不消失、
    Ctrl+X 看似无效等连锁 bug。正确行为是只记录日志，继续处理下一个事件。
    真正的连接断开由 _read_requests 的 WebSocketDisconnect 处理。
    """

    async def run() -> None:
        ws = _FakeWebSocket(raise_on_send=True)
        host = _make_host(_websocket=ws)
        # 入队两个事件
        await host._emit(BackendEvent(type="shutdown"))
        await host._emit(BackendEvent(type="line_complete"))
        # 启动写循环
        host._write_task = asyncio.create_task(host._write_loop())
        # 给写循环时间处理两个事件
        await asyncio.sleep(0.05)
        # 写循环不应退出（瞬态错误不应终止）
        assert not host._write_task.done()
        # 清理
        host._write_queue.shutdown()
        await host._write_task

    asyncio.run(run())


def test_create_background_task_keeps_strong_ref():
    """_create_background_task 保留强引用并在完成后清理。"""

    async def dummy() -> None:
        return None

    async def run() -> None:
        host = _make_host()
        task = host._create_background_task(dummy())
        # 强引用集合应包含此 task
        assert task in host._dispatch_tasks
        # 等待完成
        await task
        # 完成后回调应将其从集合移除
        assert task not in host._dispatch_tasks

    asyncio.run(run())


# === shutdown 测试 ===


def test_resolve_pending_futures_sets_default_results():
    """_resolve_pending_futures 把 pending future 设为默认值（False / ""）。"""

    async def run() -> None:
        host = _make_host()
        loop = asyncio.get_running_loop()
        perm_future: asyncio.Future[bool] = loop.create_future()
        question_future: asyncio.Future[str | dict[Any, Any]] = loop.create_future()
        host._permission_requests["perm-1"] = perm_future
        host._question_requests["q-1"] = question_future

        # 都未完成
        assert not perm_future.done()
        assert not question_future.done()

        host._resolve_pending_futures()

        # permission → False（默认拒绝）
        assert perm_future.done()
        assert perm_future.result() is False
        # question → ""（默认空答）
        assert question_future.done()
        assert question_future.result() == ""
        # 字典已清空
        assert host._permission_requests == {}
        assert host._question_requests == {}

    asyncio.run(run())


def test_graceful_shutdown_resolves_pending_futures():
    """shutdown 时 pending permission/question futures 被 resolve 为默认值。"""

    async def run() -> None:
        host = _make_host()
        loop = asyncio.get_running_loop()
        perm_future: asyncio.Future[bool] = loop.create_future()
        question_future: asyncio.Future[str | dict[Any, Any]] = loop.create_future()
        host._permission_requests["perm-1"] = perm_future
        host._question_requests["q-1"] = question_future

        # 调用 _shutdown 应触发 _resolve_pending_futures
        await host._shutdown()

        assert perm_future.done()
        assert perm_future.result() is False
        assert question_future.done()
        assert question_future.result() == ""
        # _running 应被置为 False
        assert host._running is False

    asyncio.run(run())


def test_web_host_graceful_shutdown():
    """shutdown 时写队列排空后 _write_task 退出。"""

    async def run() -> None:
        ws = _FakeWebSocket()
        host = _make_host(_websocket=ws)
        # 入队两个事件待排空
        await host._emit(BackendEvent(type="shutdown"))
        await host._emit(BackendEvent(type="error", message="drain-test"))
        # 启动写循环
        host._write_task = asyncio.create_task(host._write_loop())
        # 让写循环消费队列
        await asyncio.sleep(0.05)

        # 调用 _shutdown：会调用 _write_queue.shutdown() 唤醒 _write_loop 退出
        await host._shutdown()

        # _write_task 应已完成
        assert host._write_task is not None
        assert host._write_task.done()
        # _write_queue 已 shutdown（_emit 后续 put 抛 QueueShutDown）
        with pytest.raises(QueueShutDown):
            host._write_queue.put_nowait(BackendEvent(type="error", message="after-shutdown"))
        # _running 应被置为 False
        assert host._running is False
        # 两个事件都已通过 WebSocket 发送
        assert len(ws.sent) == 2

    asyncio.run(run())


def test_shutdown_is_idempotent():
    """_shutdown 可重复调用（disconnect handler + finally 均可能调用）。"""

    async def run() -> None:
        host = _make_host()
        # 第一次调用
        await host._shutdown()
        assert host._running is False
        # 第二次调用不应抛异常
        await host._shutdown()
        assert host._running is False

    asyncio.run(run())
