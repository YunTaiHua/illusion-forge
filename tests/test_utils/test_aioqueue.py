"""异步队列 shutdown 语义单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from illusion_forge.utils.aioqueue import Queue, QueueShutDown


def test_put_get_basic():
    """正常 put/get 交互。"""
    q: Queue[int] = Queue()

    async def run():
        await q.put(1)
        await q.put(2)
        assert await q.get() == 1
        assert await q.get() == 2

    asyncio.run(run())


def test_put_nowait_get_nowait_basic():
    """非阻塞 put/get。"""
    q: Queue[int] = Queue()
    q.put_nowait(42)
    assert q.get_nowait() == 42


def test_shutdown_raises_on_get_when_empty():
    """shutdown 后空队列 get() 抛 QueueShutDown。"""
    q: Queue[int] = Queue()

    async def run():
        q.shutdown()
        with pytest.raises(QueueShutDown):
            await q.get()

    asyncio.run(run())


def test_shutdown_immediate_clears_pending():
    """shutdown(immediate=True) 清空待处理项。"""
    q: Queue[int] = Queue()
    q.put_nowait(1)
    q.put_nowait(2)
    q.put_nowait(3)
    q.shutdown(immediate=True)
    with pytest.raises(QueueShutDown):
        q.get_nowait()


def test_put_after_shutdown_raises():
    """shutdown 后 put() 抛 QueueShutDown。"""
    q: Queue[int] = Queue()
    q.shutdown()

    async def run():
        with pytest.raises(QueueShutDown):
            await q.put(99)

    asyncio.run(run())


def test_shutdown_drains_pending_before_raising():
    """shutdown(默认) 保留待处理项，getter 取完后再抛 QueueShutDown。"""
    q: Queue[int] = Queue()
    q.put_nowait(10)
    q.put_nowait(20)
    q.shutdown()
    assert q.get_nowait() == 10
    assert q.get_nowait() == 20
    with pytest.raises(QueueShutDown):
        q.get_nowait()


def test_multiple_getters_all_wake():
    """N 个 getter 在 shutdown 时全部被唤醒。"""
    q: Queue[int] = Queue()

    async def getter(results: list[str]):
        try:
            await q.get()
            results.append("ok")
        except QueueShutDown:
            results.append("shutdown")

    async def run():
        results: list[str] = []
        tasks = [asyncio.create_task(getter(results)) for _ in range(3)]
        await asyncio.sleep(0.05)
        q.shutdown()
        await asyncio.gather(*tasks)
        assert results == ["shutdown", "shutdown", "shutdown"]

    asyncio.run(run())


def test_get_nowait_on_empty_raises_queueempty_not_shutdown():
    """空队列未 shutdown 时 get_nowait 抛 QueueEmpty（不是 QueueShutDown）。"""
    q: Queue[int] = Queue()
    with pytest.raises(asyncio.QueueEmpty):
        q.get_nowait()
