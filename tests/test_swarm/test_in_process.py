"""Tests for InProcessBackend: spawn, shutdown, send_message."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from illusion_forge.swarm.agent_executor import (
    AgentAbortController,
    AgentExecutionContext,
    get_agent_context,
    set_agent_context,
)
from illusion_forge.swarm.in_process import InProcessBackend
from illusion_forge.swarm.types import TeammateMessage, TeammateSpawnConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def spawn_config():
    return TeammateSpawnConfig(
        name="worker",
        team="test-team",
        prompt="hello",
        cwd="/tmp",
        parent_session_id="sess-001",
    )


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return InProcessBackend()


# ---------------------------------------------------------------------------
# AgentExecutionContext
# ---------------------------------------------------------------------------


def test_agent_context_defaults():
    ctx = AgentExecutionContext(
        agent_id="w@t",
        agent_name="w",
    )
    assert ctx.color is None if hasattr(ctx, 'color') else True
    assert not ctx.abort_controller.is_cancelled


# ---------------------------------------------------------------------------
# ContextVar get / set
# ---------------------------------------------------------------------------


def test_get_agent_context_returns_none_outside_task():
    # Force reset to ensure clean state (ContextVar may leak between tests)
    from illusion_forge.swarm.agent_executor import _agent_context_var
    token = _agent_context_var.set(None)
    try:
        result = get_agent_context()
        assert result is None
    finally:
        _agent_context_var.reset(token)


async def test_set_and_get_agent_context():
    ctx = AgentExecutionContext(agent_id="x@y", agent_name="x")
    set_agent_context(ctx)
    assert get_agent_context() is ctx
    # Clean up
    from illusion_forge.swarm.agent_executor import _agent_context_var
    _agent_context_var.set(None)


# ---------------------------------------------------------------------------
# AgentAbortController
# ---------------------------------------------------------------------------


def test_abort_controller_graceful():
    ctrl = AgentAbortController()
    assert not ctrl.is_cancelled
    ctrl.request_cancel(reason="test")
    assert ctrl.is_cancelled
    assert ctrl.cancel_event.is_set()
    assert not ctrl.force_cancel.is_set()


def test_abort_controller_force():
    ctrl = AgentAbortController()
    ctrl.request_cancel(reason="force", force=True)
    assert ctrl.is_cancelled
    assert ctrl.cancel_event.is_set()
    assert ctrl.force_cancel.is_set()


# ---------------------------------------------------------------------------
# InProcessBackend.spawn
# ---------------------------------------------------------------------------


async def test_spawn_returns_success_result(backend, spawn_config):
    result = await backend.spawn(spawn_config)
    assert result.success is True
    assert result.agent_id == "worker@test-team"
    assert result.backend_type == "in_process"
    assert result.task_id.startswith("in_process_")


async def test_spawn_duplicate_returns_failure(backend, spawn_config):
    await backend.spawn(spawn_config)
    result = await backend.spawn(spawn_config)
    assert result.success is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# InProcessBackend.shutdown
# ---------------------------------------------------------------------------


async def test_shutdown_unknown_agent_returns_false(backend):
    result = await backend.shutdown("nonexistent@team")
    assert result is False


async def test_graceful_shutdown(backend, spawn_config):
    await backend.spawn(spawn_config)
    result = await backend.shutdown("worker@test-team", timeout=2.0)
    assert result is True


async def test_force_shutdown(backend, spawn_config):
    await backend.spawn(spawn_config)
    result = await backend.shutdown("worker@test-team", force=True, timeout=2.0)
    assert result is True


# ---------------------------------------------------------------------------
# InProcessBackend.send_message
# ---------------------------------------------------------------------------


async def test_send_message_to_active_agent(backend, spawn_config):
    await backend.spawn(spawn_config)
    # Give the asyncio task time to start and register the agent
    for _ in range(10):
        await asyncio.sleep(0.1)
        if "worker@test-team" in [a[0] for a in backend.list_agents()]:
            break
    msg = TeammateMessage(text="work on it", from_agent="leader")
    # Should not raise
    await backend.send_message("worker@test-team", msg)
    await backend.shutdown("worker@test-team", force=True, timeout=2.0)


async def test_send_message_invalid_agent_id_raises(backend):
    with pytest.raises(ValueError):
        await backend.send_message("no-at-sign", TeammateMessage(text="hi", from_agent="l"))


# ---------------------------------------------------------------------------
# list_agents / shutdown_all
# ---------------------------------------------------------------------------


async def test_list_agents(backend, spawn_config):
    await backend.spawn(spawn_config)
    agents = backend.list_agents()
    assert len(agents) == 1
    assert agents[0][0] == "worker@test-team"


async def test_shutdown_all(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for name in ("a", "b"):
        cfg = TeammateSpawnConfig(
            name=name,
            team="t",
            prompt="run",
            cwd="/tmp",
            parent_session_id="s",
        )
        await backend.spawn(cfg)

    await backend.shutdown_all(force=True, timeout=2.0)
    assert backend.list_agents() == []


# ---------------------------------------------------------------------------
# _run_agent: query_context-aware dispatch (Task 3.4 / 3.5)
# ---------------------------------------------------------------------------


async def test_run_agent_calls_run_agent_in_process_when_query_context_provided(
    tmp_path, monkeypatch
):
    """当 TeammateSpawnConfig 提供 query_context 和 parent_registry 时，_run_agent 应调用 run_agent_in_process。"""
    from types import SimpleNamespace

    from illusion_forge.swarm.agent_executor import AgentResult, TaskNotification

    # mock run_agent_in_process
    call_log: dict = {}

    async def _fake_run_agent_in_process(
        config,
        query_context,
        parent_registry,
        *,
        is_async=False,
        existing_context=None,
        on_progress=None,
    ):
        call_log["called"] = True
        call_log["is_async"] = is_async
        return AgentResult(
            agent_id="test-agent",
            success=True,
            notification=TaskNotification(
                task_id="test-agent",
                status="completed",
                summary="done",
                result=None,
                usage=None,
            ),
        )

    monkeypatch.setattr(
        "illusion_forge.swarm.agent_executor.run_agent_in_process", _fake_run_agent_in_process
    )

    backend = InProcessBackend()
    config = TeammateSpawnConfig(
        name="worker",
        team="test-team",
        prompt="hello",
        cwd=str(tmp_path),
        parent_session_id="sess-001",
        query_context=SimpleNamespace(),  # 非 None
        parent_registry=SimpleNamespace(),  # 非 None
    )
    result = await backend.spawn(config)
    assert result.success

    await asyncio.sleep(0.3)  # 等待 _run_agent 执行

    assert call_log.get("called") is True
    assert call_log.get("is_async") is True

    await backend.shutdown_all()


async def test_run_agent_falls_back_to_stub_without_query_context(tmp_path, monkeypatch):
    """当 TeammateSpawnConfig 未提供 query_context 时，_run_agent 应回退到 stub 行为。"""
    # mock run_agent_in_process - 若被调用则失败
    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("run_agent_in_process should not be called without query_context")

    monkeypatch.setattr(
        "illusion_forge.swarm.agent_executor.run_agent_in_process", _should_not_be_called
    )

    backend = InProcessBackend()
    config = TeammateSpawnConfig(
        name="worker",
        team="test-team",
        prompt="hello",
        cwd=str(tmp_path),
        parent_session_id="sess-001",
        # query_context 和 parent_registry 未提供
    )
    result = await backend.spawn(config)
    assert result.success

    await asyncio.sleep(0.2)
    await backend.shutdown_all()
    # 未崩溃即通过
