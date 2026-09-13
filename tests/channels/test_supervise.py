"""渠道守护进程看门狗测试

验证 _supervise 在 runner.run() 抛异常后带退避自动重启，
在 stop_event 触发后停止。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_supervise_restarts_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """runner.run() 抛异常后应重启，直到成功或 stop_event 触发"""
    from illusion_forge.channels import serve

    # 压缩退避，加速测试
    monkeypatch.setattr(serve, "SUPERVISOR_BACKOFF_SECONDS", (0.01, 0.01, 0.01))

    runner = MagicMock()
    call_count = {"n": 0}

    async def flaky_run() -> None:
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError("transient channel failure")
        # 第 3 次成功后，通过 stop_event 让循环退出
        stop_event.set()

    runner.run = flaky_run
    runner.shutdown = AsyncMock()

    stop_event = asyncio.Event()
    await serve._supervise(runner, stop_event)

    assert call_count["n"] == 3, "应在异常后重启直至成功"


@pytest.mark.asyncio
async def test_supervise_stops_on_stop_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop_event 触发后应停止重启并退出（shutdown 由 _serve_async 外层负责）"""
    from illusion_forge.channels import serve

    monkeypatch.setattr(serve, "SUPERVISOR_BACKOFF_SECONDS", (0.01, 0.01, 0.01))

    runner = MagicMock()
    run_count = {"n": 0}

    async def always_fail() -> None:
        run_count["n"] += 1
        raise RuntimeError("always fails")

    runner.run = always_fail

    stop_event = asyncio.Event()
    # 启动 supervise，50ms 后触发停止
    task = asyncio.create_task(serve._supervise(runner, stop_event))
    await asyncio.sleep(0.05)
    runs_before_stop = run_count["n"]
    stop_event.set()
    await task  # 应在退避窗口内退出

    # stop 后不再有新的 run 调用
    await asyncio.sleep(0.05)
    assert run_count["n"] == runs_before_stop, "stop_event 后不应再重启 runner"
