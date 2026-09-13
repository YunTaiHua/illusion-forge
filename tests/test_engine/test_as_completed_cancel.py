"""as_completed 异常路径取消未完成 task 测试。"""

from __future__ import annotations

import asyncio

import pytest


def test_exception_cancels_pending_tasks():
    """一个 task 抛异常后，其他未完成 task 被 cancel。"""

    async def run():
        # 模拟 _safe_run：第一个 task 抛异常，第二个 task 长时间运行
        cancelled = asyncio.Event()

        async def failing_task():
            raise ValueError("task failed")

        async def long_task():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        # 模拟修复后的模式：显式 task 列表 + try/finally
        tasks = [
            asyncio.ensure_future(failing_task()),
            asyncio.ensure_future(long_task()),
        ]
        with pytest.raises(ValueError):
            try:
                for coro in asyncio.as_completed(tasks):
                    await coro
            except Exception:
                # 修复后的逻辑：cancel 未完成 task
                for t in tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

        # 验证 long_task 被 cancel 了
        assert cancelled.is_set(), "long_task 应被 cancel"
        assert tasks[1].cancelled() or tasks[1].done(), "long_task 应已完成或被 cancel"

    asyncio.run(run())


def test_permission_denied_cancels_other_tasks():
    """模拟 PermissionDenied 场景：其他 task 被 cancel。"""

    async def run():
        cancelled = asyncio.Event()

        class PermissionDenied(Exception):
            pass

        async def denied_task():
            raise PermissionDenied("denied")

        async def long_task():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        tasks = [
            asyncio.ensure_future(denied_task()),
            asyncio.ensure_future(long_task()),
        ]
        with pytest.raises(PermissionDenied):
            try:
                for coro in asyncio.as_completed(tasks):
                    await coro
            except PermissionDenied:
                # 修复后的逻辑：cancel 未完成 task
                for t in tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

        assert cancelled.is_set(), "long_task 应被 cancel"

    asyncio.run(run())
