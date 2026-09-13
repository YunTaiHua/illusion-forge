"""fire-and-forget 强引用模式测试。"""

from __future__ import annotations

import asyncio
import gc


def test_background_task_survives_gc():
    """强引用 task 不被 GC 抢收。"""

    async def run():
        results: list[str] = []
        tasks: set[asyncio.Task[None]] = set()

        async def slow_task():
            await asyncio.sleep(0.1)
            results.append("done")

        # 模拟 _create_background_task 模式
        task = asyncio.create_task(slow_task())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

        # 触发 GC
        gc.collect()
        await asyncio.sleep(0)

        # task 仍存在
        assert len(tasks) == 1, "task 应未被 GC 回收"

        # 等待完成
        await asyncio.gather(*tasks)
        assert results == ["done"]
        # 完成后从集合移除
        assert len(tasks) == 0

    asyncio.run(run())


def test_dispatch_tasks_set_cleanup():
    """task 完成后从 _dispatch_tasks 移除。"""

    async def run():
        tasks: set[asyncio.Task[None]] = set()

        async def quick_task():
            pass

        for _ in range(5):
            task = asyncio.create_task(quick_task())
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        assert len(tasks) == 5
        await asyncio.gather(*tasks)
        # 所有 task 完成后集合应清空
        assert len(tasks) == 0

    asyncio.run(run())


def test_module_level_set_pattern():
    """模块级 set 模式：模块级函数中的 task 强引用。"""

    async def run():
        module_tasks: set[asyncio.Task[None]] = set()

        def _create_module_task(coro):
            task = asyncio.create_task(coro)
            module_tasks.add(task)
            task.add_done_callback(module_tasks.discard)
            return task

        executed: list[int] = []

        async def work(n: int):
            await asyncio.sleep(0.05)
            executed.append(n)

        # 创建 3 个模块级 task
        for i in range(3):
            _create_module_task(work(i))

        assert len(module_tasks) == 3
        gc.collect()
        await asyncio.gather(*module_tasks)
        assert sorted(executed) == [0, 1, 2]
        assert len(module_tasks) == 0

    asyncio.run(run())


def test_qq_streaming_controller_dispatch_tasks_initialized():
    """QQStreamingController 通过基类继承 _dispatch_tasks 集合。"""
    from illusion_forge.channels.qq.streaming import QQStreamingController
    from unittest.mock import AsyncMock
    controller = QQStreamingController(
        session=AsyncMock(), token="t", openid="o", msg_id="m"
    )
    # _dispatch_tasks 由 BaseStreamingController.__init__ 初始化
    assert hasattr(controller, "_dispatch_tasks")
    assert isinstance(controller._dispatch_tasks, set)


def test_feishu_streaming_controller_dispatch_tasks_initialized():
    """FeishuStreamingCardController 初始化 _dispatch_tasks 集合。"""
    from illusion_forge.channels.feishu.streaming import FeishuStreamingCardController
    from unittest.mock import MagicMock
    controller = FeishuStreamingCardController(MagicMock(), "ou_user1")
    assert hasattr(controller, "_dispatch_tasks")
    assert isinstance(controller._dispatch_tasks, set)
