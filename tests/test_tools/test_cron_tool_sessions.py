"""cron_tool 指定会话与投递目标更新测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from illusion_forge.tools.base import ToolExecutionContext, ToolResult
from illusion_forge.tools.cron_tool import CronTool, CronToolInput


def _context(tmp_path: Path, session_id: str | None = "sess_current") -> ToolExecutionContext:
    """构造工具执行上下文（默认带当前会话 ID）。"""
    metadata: dict = {"session_id": session_id} if session_id else {}
    return ToolExecutionContext(cwd=tmp_path, metadata=metadata)


async def _run_add(
    context: ToolExecutionContext,
    *,
    session_id: str | None = None,
    name: str = "job-a",
) -> ToolResult:
    """执行 add 的辅助函数（跳过 cron 表达式校验要求）。"""
    tool = CronTool()
    args = CronToolInput(
        action="add",
        name=name,
        schedule="0 9 * * *",
        prompt="test prompt",
        session_id=session_id,
    )
    return await tool.execute(args, context)


async def _run_update(
    context: ToolExecutionContext,
    *,
    name: str = "job-a",
    session_id: str | None = None,
    deliver_to: list[str] | None = None,
) -> ToolResult:
    """执行 update 的辅助函数。"""
    tool = CronTool()
    kwargs: dict = {"action": "update", "name": name}
    if session_id is not None:
        kwargs["session_id"] = session_id
    if deliver_to is not None:
        kwargs["deliver_to"] = deliver_to
    args = CronToolInput(**kwargs)
    return await tool.execute(args, context)


def _load_jobs() -> list[dict]:
    from illusion_forge.services.cron import load_cron_jobs

    return load_cron_jobs()


def _find_job(name: str) -> dict | None:
    from illusion_forge.services.cron import get_cron_job_by_name

    return get_cron_job_by_name(name)


@pytest.fixture(autouse=True)
def _tmp_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """将 cron 注册表重定向到临时目录。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))


@pytest.mark.asyncio
async def test_add_without_session_id_keeps_new_session(tmp_path: Path) -> None:
    """add 未传 session_id（None）→ 不设置字段（独立新会话默认行为）。"""
    result = await _run_add(_context(tmp_path), session_id=None)
    assert not result.is_error
    job = _find_job("job-a")
    assert job is not None
    assert "session_id" not in job


@pytest.mark.asyncio
async def test_add_empty_session_id_uses_current_session(tmp_path: Path) -> None:
    """add 传空串 → 设置为当前活跃会话 ID。"""
    result = await _run_add(_context(tmp_path, session_id="sess_current"), session_id="")
    assert not result.is_error
    job = _find_job("job-a")
    assert job is not None
    assert job["session_id"] == "sess_current"


@pytest.mark.asyncio
async def test_add_empty_session_id_without_context_session(tmp_path: Path) -> None:
    """add 传空串但上下文无会话 ID → 不设置（降级为新会话）。"""
    result = await _run_add(_context(tmp_path, session_id=None), session_id="")
    assert not result.is_error
    job = _find_job("job-a")
    assert job is not None
    assert "session_id" not in job


@pytest.mark.asyncio
async def test_add_explicit_session_id(tmp_path: Path) -> None:
    """add 传具体值 → 使用指定会话。"""
    result = await _run_add(_context(tmp_path), session_id="sess_target")
    assert not result.is_error
    job = _find_job("job-a")
    assert job is not None
    assert job["session_id"] == "sess_target"


@pytest.mark.asyncio
async def test_update_deliver_to(tmp_path: Path) -> None:
    """update 更新 deliver_to 投递目标。"""
    await _run_add(_context(tmp_path))
    result = await _run_update(
        _context(tmp_path),
        deliver_to=["weixin:abc", "feishu:ou_123"],
    )
    assert not result.is_error
    assert "deliver_to" in result.output
    job = _find_job("job-a")
    assert job is not None
    assert job["deliver_to"] == ["weixin:abc", "feishu:ou_123"]


@pytest.mark.asyncio
async def test_update_deliver_to_cleared(tmp_path: Path) -> None:
    """update 传空列表 → 清除投递目标。"""
    await _run_add(_context(tmp_path))
    await _run_update(_context(tmp_path), deliver_to=["weixin:abc"])
    result = await _run_update(_context(tmp_path), deliver_to=[])
    assert not result.is_error
    job = _find_job("job-a")
    assert job is not None
    assert job["deliver_to"] == []


@pytest.mark.asyncio
async def test_update_session_id_explicit(tmp_path: Path) -> None:
    """update 传具体值 → 更新为指定会话。"""
    await _run_add(_context(tmp_path))
    result = await _run_update(_context(tmp_path), session_id="sess_target")
    assert not result.is_error
    assert "session_id=sess_target" in result.output
    job = _find_job("job-a")
    assert job["session_id"] == "sess_target"


@pytest.mark.asyncio
async def test_update_session_id_empty_uses_current(tmp_path: Path) -> None:
    """update 传空串 → 更新为当前活跃会话。"""
    await _run_add(_context(tmp_path))
    result = await _run_update(_context(tmp_path, session_id="sess_current"), session_id="")
    assert not result.is_error
    job = _find_job("job-a")
    assert job["session_id"] == "sess_current"


@pytest.mark.asyncio
async def test_update_session_id_not_provided_keeps_existing(tmp_path: Path) -> None:
    """update 不传 session_id → 保持原值（不被清除）。"""
    await _run_add(_context(tmp_path), session_id="sess_orig")
    result = await _run_update(_context(tmp_path))
    # 无字段更新时工具返回提示错误（既有行为），session_id 必须保持原值
    assert result.is_error
    job = _find_job("job-a")
    assert job["session_id"] == "sess_orig"
