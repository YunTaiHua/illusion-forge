"""CAD 会话事件广播
==================

宿主线程（非 asyncio 线程）到 Web 前端的事件桥梁。订阅方
（ws_host）回调内必须用 ``loop.call_soon_threadsafe`` 回到事件循环。

主要组件：
    - subscribe_cad_broadcast: 订阅会话事件，返回取消订阅函数
    - broadcast_cad_update: 广播一次更新（回调异常互相隔离）
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

# 回调签名：callback(payload_dict) -> None
_listeners: list[Callable[[dict[str, Any]], None]] = []
_lock = threading.Lock()


def subscribe_cad_broadcast(callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
    """订阅 CAD 会话事件广播，返回取消订阅函数。"""
    with _lock:
        _listeners.append(callback)

    def _unsubscribe() -> None:
        with _lock:
            try:
                _listeners.remove(callback)
            except ValueError:
                pass

    return _unsubscribe


def broadcast_cad_update(payload: dict[str, Any]) -> None:
    """广播一次 CAD 会话更新（线程安全；回调异常互相隔离）。"""
    with _lock:
        callbacks = list(_listeners)
    for callback in callbacks:
        try:
            callback(payload)
        except Exception:
            log.exception("CAD 事件广播回调异常")
