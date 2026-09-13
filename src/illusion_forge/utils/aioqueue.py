"""
异步队列模块
============

本模块提供支持 shutdown 语义的 asyncio.Queue 子类，用于后端主机写循环的
优雅关闭。Python 3.13+ 使用原生 asyncio.QueueShutDown，低版本使用哨兵 polyfill。

主要功能：
    - Queue: 带 shutdown() 方法的异步队列
    - QueueShutDown: 队列关闭后操作抛出的异常
"""

from __future__ import annotations

import asyncio
import sys
from typing import TypeVar

T = TypeVar("T")

if sys.version_info >= (3, 13):
    QueueShutDown = asyncio.QueueShutDown  # type: ignore[assignment]

    class Queue(asyncio.Queue[T]):
        """支持 shutdown 的异步队列（Python 3.13+ 原生实现）。"""

else:

    class QueueShutDown(Exception):
        """队列关闭后执行操作时抛出。"""

    class _Shutdown:
        """队列关闭哨兵，用于唤醒所有等待中的 getter。"""

    _SHUTDOWN = _Shutdown()

    class Queue(asyncio.Queue[T | _Shutdown]):
        """支持 shutdown 的异步队列（Python < 3.13 哨兵 polyfill）。

        通过向队列投入 _Shutdown 哨兵唤醒所有等待中的 getter，getter 收到
        哨兵后抛出 QueueShutDown。
        """

        def __init__(self) -> None:
            super().__init__()
            self._shutdown = False

        def shutdown(self, immediate: bool = False) -> None:
            """关闭队列，唤醒所有等待中的 getter。

            Args:
                immediate: True 时清空待处理项后关闭；False 时保留待处理项
                    供 getter 取走后再抛 QueueShutDown。
            """
            if self._shutdown:
                return
            self._shutdown = True
            if immediate:
                self._queue.clear()  # type: ignore[attr-defined]

            getters = list(getattr(self, "_getters", []))
            count = max(1, len(getters))
            self._enqueue_shutdown(count)

        def _enqueue_shutdown(self, count: int) -> None:
            """向队列投入 count 个哨兵。"""
            for _ in range(count):
                try:
                    super().put_nowait(_SHUTDOWN)
                except asyncio.QueueFull:
                    self._queue.clear()  # type: ignore[attr-defined]
                    super().put_nowait(_SHUTDOWN)

        async def get(self) -> T:
            """从队列取出一个项，收到哨兵时抛 QueueShutDown。"""
            if self._shutdown and self.empty():
                raise QueueShutDown
            item = await super().get()
            if isinstance(item, _Shutdown):
                raise QueueShutDown
            return item

        def get_nowait(self) -> T:
            """非阻塞取出一个项，收到哨兵时抛 QueueShutDown。"""
            if self._shutdown and self.empty():
                raise QueueShutDown
            item = super().get_nowait()
            if isinstance(item, _Shutdown):
                raise QueueShutDown
            return item

        async def put(self, item: T) -> None:  # type: ignore[override]
            """向队列投入一个项，队列已关闭时抛 QueueShutDown。"""
            if self._shutdown:
                raise QueueShutDown
            await super().put(item)

        def put_nowait(self, item: T) -> None:  # type: ignore[override]
            """非阻塞投入一个项，队列已关闭时抛 QueueShutDown。"""
            if self._shutdown:
                raise QueueShutDown
            super().put_nowait(item)
