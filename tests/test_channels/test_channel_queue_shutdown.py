"""渠道入站 queue shutdown 哨兵 + _pending_replies Future resolve 测试。"""
from __future__ import annotations

import asyncio

import pytest

from illusion_forge.utils.aioqueue import Queue


def test_feishu_listen_exits_on_shutdown():
    """FeishuChannel.shutdown 调用 queue.shutdown 唤醒 listen 协程。

    listen 协程原本 await queue.get() 阻塞，shutdown 通过 queue.shutdown()
    投递哨兵唤醒 getter，getter 抛 QueueShutDown，listen 捕获后 break。
    关键：唤醒应在 200ms 内完成，证明走 queue.shutdown() 路径
    （而非旧的 1s wait_for 轮询 _stop_event 路径）。
    """

    async def run():
        from illusion_forge.channels.feishu.adapter import FeishuChannel

        # 用 __new__ 跳过 __init__，仅设置必要属性
        ch = FeishuChannel.__new__(FeishuChannel)
        ch._queue = Queue()
        ch._stop_event = asyncio.Event()
        ch._client = None
        ch._ws = None
        ch._ws_future = None
        ch._ws_executor = None

        # 启动 listen async generator，取首个 __anext__
        gen = ch.listen()
        first_anext = asyncio.create_task(gen.__anext__())
        # 让事件循环跑一会，让 listen 进入 await queue.get() 等待
        await asyncio.sleep(0.05)
        assert not first_anext.done(), "listen 不应在无消息时退出"

        # 调用 shutdown：触发 _queue.shutdown() 唤醒 listen
        await ch.shutdown()

        # listen 应在 200ms 内退出（QueueShutDown → break → StopAsyncIteration）
        # 旧的 wait_for(queue.get(), timeout=1.0) 路径需 1s 才醒，200ms 必然失败
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(first_anext, timeout=0.2)

        # _stop_event 应被设置（shutdown 副作用）
        assert ch._stop_event.is_set()

    asyncio.run(run())


def test_qq_listen_exits_on_shutdown():
    """QQChannel.shutdown 调用 queue.shutdown 唤醒 listen 协程。"""

    async def run():
        from illusion_forge.channels.qq.adapter import QQChannel

        ch = QQChannel.__new__(QQChannel)
        ch._queue = Queue()
        ch._stop_event = asyncio.Event()
        ch._ws_client = None
        ch._session = None

        gen = ch.listen()
        first_anext = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.05)
        assert not first_anext.done(), "listen 不应在无消息时退出"

        await ch.shutdown()

        # 200ms 内退出，证明走 queue.shutdown() 路径而非 1s 轮询
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(first_anext, timeout=0.2)

        assert ch._stop_event.is_set()

    asyncio.run(run())


def test_feishu_listen_yields_then_exits_on_shutdown():
    """FeishuChannel.listen 先 yield 已入队消息，shutdown 后退出。"""

    async def run():
        from illusion_forge.channels.base import InboundMessage
        from illusion_forge.channels.feishu.adapter import FeishuChannel

        ch = FeishuChannel.__new__(FeishuChannel)
        ch._queue = Queue()
        ch._stop_event = asyncio.Event()
        ch._client = None
        ch._ws = None
        ch._ws_future = None
        ch._ws_executor = None

        # 预先放入一条消息
        msg = InboundMessage(
            text="hi", chat_id="c1", chat_type="dm",
            user_id="u1", user_name="u", message_id="m1",
        )
        await ch._queue.put(msg)

        gen = ch.listen()
        first = await gen.__anext__()
        assert first is msg

        # 启动下一次 __anext__（会阻塞在 queue.get）
        next_anext = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.05)
        assert not next_anext.done()

        await ch.shutdown()
        # 200ms 内退出
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(next_anext, timeout=0.2)

    asyncio.run(run())


def test_channel_runner_resolves_pending_replies():
    """ChannelRunner.shutdown resolve _pending_replies Future 为空串。

    场景：agent turn 通过 _wait_reply 创建 Future 等待用户回复，
    若 shutdown 时未 resolve，agent turn 会卡 300s 超时。
    修复后 ChannelRunner.shutdown 在关闭渠道前 resolve 所有 pending Future 为 ""。
    """

    async def run():
        from illusion_forge.channels import ChannelRunner

        # 用 __new__ 跳过 __init__，仅设置必要属性
        runner = ChannelRunner.__new__(ChannelRunner)
        runner._stop = False

        # mock channel：shutdown() 为 noop
        class _FakeChannel:
            async def shutdown(self) -> None:
                pass

        runner.channel = _FakeChannel()

        # 在事件循环内创建 Future（绑定到当前 loop）
        loop = asyncio.get_running_loop()
        fut1: asyncio.Future[str] = loop.create_future()
        fut2: asyncio.Future[str] = loop.create_future()
        runner._pending_replies = {"chat1": fut1, "chat2": fut2}

        # 启动一个等待 fut1 的协程，模拟 agent turn 在等回复
        async def wait_reply():
            return await asyncio.wait_for(fut1, timeout=10.0)

        waiter = asyncio.create_task(wait_reply())
        await asyncio.sleep(0.05)
        assert not waiter.done(), "agent turn 应卡在等回复"

        # 调用 shutdown
        await runner.shutdown()

        # waiter 应在 1s 内被唤醒并拿到 ""
        result = await asyncio.wait_for(waiter, timeout=1.0)
        assert result == ""

        # fut2 也应被 resolve 为 ""
        assert fut2.done() and fut2.result() == ""

        # _pending_replies 应被清空
        assert runner._pending_replies == {}

        # _stop 应被置 True
        assert runner._stop is True

    asyncio.run(run())


def test_channel_runner_shutdown_no_pending_replies():
    """ChannelRunner.shutdown 在无 pending replies 时也正常工作。"""

    async def run():
        from illusion_forge.channels import ChannelRunner

        runner = ChannelRunner.__new__(ChannelRunner)
        runner._stop = False

        class _FakeChannel:
            async def shutdown(self) -> None:
                pass

        runner.channel = _FakeChannel()
        runner._pending_replies = {}

        await runner.shutdown()
        assert runner._pending_replies == {}
        assert runner._stop is True

    asyncio.run(run())
