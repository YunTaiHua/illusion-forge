"""rename_handler 单元测试。"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from illusion_forge.commands.session import rename_handler
from illusion_forge.commands.types import CommandContext
from illusion_forge.services.session_storage import (
    get_project_session_dir,
    list_session_snapshots,
    read_meta,
    write_index,
    write_meta,
)


def _make_context(tmp_path: Path, engine=None, session_id: str = "test_sid") -> CommandContext:
    """构造测试 CommandContext。"""
    return CommandContext(
        engine=engine or MagicMock(),
        cwd=str(tmp_path),
        session_id=session_id,
    )


def _write_session(tmp_path: Path, sid: str, summary: str = "test summary", updated_at: float | None = None) -> None:
    """写入测试用会话 meta.json + index.json。"""
    ts = updated_at if updated_at is not None else time.time()
    write_meta(tmp_path, sid, {
        "session_id": sid,
        "cwd": str(tmp_path),
        "model": "claude-test",
        "created_at": ts,
        "updated_at": ts,
        "summary": summary,
        "message_count": 2,
        "turn_count": 1,
    })
    write_index(tmp_path, sid)


@pytest.mark.asyncio
async def test_rename_current_session(tmp_path: Path) -> None:
    """无引用词时，重命名当前会话。"""
    _write_session(tmp_path, "test_sid")
    ctx = _make_context(tmp_path)

    result = await rename_handler("my new name", ctx)

    assert result.refresh_state is True
    meta = read_meta(tmp_path, "test_sid")
    assert meta is not None
    assert meta["title"] == "my new name"
    assert "my new name" in (result.message or "")


@pytest.mark.asyncio
async def test_rename_via_number_reference(tmp_path: Path) -> None:
    """#N 引用重命名指定会话（按 updated_at 降序排列）。"""
    base = time.time()
    _write_session(tmp_path, "abc123", summary="first", updated_at=base)
    _write_session(tmp_path, "def456", summary="second", updated_at=base + 1)
    ctx = _make_context(tmp_path, session_id="other_sid")

    # def456 更新 → #1, abc123 较旧 → #2
    result = await rename_handler("#1 renamed via number", ctx)

    meta = read_meta(tmp_path, "def456")
    assert meta is not None
    assert meta["title"] == "renamed via number"
    assert "renamed via number" in (result.message or "")


@pytest.mark.asyncio
async def test_rename_via_session_id(tmp_path: Path) -> None:
    """12 位 hex 词时视为 session_id 引用。"""
    _write_session(tmp_path, "abc123def456")
    ctx = _make_context(tmp_path, session_id="other_sid")

    result = await rename_handler("abc123def456 custom title", ctx)

    meta = read_meta(tmp_path, "abc123def456")
    assert meta is not None
    assert meta["title"] == "custom title"


@pytest.mark.asyncio
async def test_rename_clear(tmp_path: Path) -> None:
    """--clear 清除当前会话的 title。"""
    _write_session(tmp_path, "test_sid")
    write_meta(tmp_path, "test_sid", {
        **read_meta(tmp_path, "test_sid"),  # type: ignore[arg-type]
        "title": "existing title",
    })
    ctx = _make_context(tmp_path)

    result = await rename_handler("--clear", ctx)

    assert result.refresh_state is True
    meta = read_meta(tmp_path, "test_sid")
    assert meta is not None
    assert "title" not in meta
    assert "清除" in (result.message or "") or "cleared" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_rename_empty_name(tmp_path: Path) -> None:
    """纯空白字符输入视为无参数（列出会话）。"""
    _write_session(tmp_path, "test_sid")
    ctx = _make_context(tmp_path)

    result = await rename_handler("   ", ctx)

    meta = read_meta(tmp_path, "test_sid")
    assert meta is not None
    assert "title" not in meta
    # 空白输入 strip 后为空 → 进入无参数分支，列出会话
    message = result.message or ""
    assert "#1" in message
    assert result.refresh_state is False


@pytest.mark.asyncio
async def test_rename_empty_name_after_reference(tmp_path: Path) -> None:
    """引用词 + 空白名称被拒绝（返回 empty_name 提示）。"""
    _write_session(tmp_path, "test_sid")
    ctx = _make_context(tmp_path)

    result = await rename_handler("#1   ", ctx)

    meta = read_meta(tmp_path, "test_sid")
    assert meta is not None
    assert "title" not in meta
    assert "空" in (result.message or "") or "empty" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_rename_invalid_number_reference(tmp_path: Path) -> None:
    """越界的 #N 返回错误提示。"""
    _write_session(tmp_path, "abc123")
    ctx = _make_context(tmp_path)

    result = await rename_handler("#99 oops", ctx)

    meta = read_meta(tmp_path, "abc123")
    assert meta is not None
    assert "title" not in meta
    assert "Invalid" in (result.message or "") or "invalid" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_rename_nonexistent_session(tmp_path: Path) -> None:
    """不存在的 session_id 返回未找到提示。"""
    ctx = _make_context(tmp_path)

    result = await rename_handler("deadbeef1234 some name", ctx)

    assert "not found" in (result.message or "").lower() or "未找到" in (result.message or "")


@pytest.mark.asyncio
async def test_rename_preserves_title_after_meta_rewrite(tmp_path: Path) -> None:
    """模拟 _update_session_meta 重写后 title 不被覆盖。"""
    _write_session(tmp_path, "test_sid")
    ctx = _make_context(tmp_path)

    await rename_handler("persistent title", ctx)

    # 模拟 _update_session_meta 的行为：保留 title 字段
    meta = read_meta(tmp_path, "test_sid")
    assert meta is not None
    updated = {**meta, "summary": "new summary", "updated_at": time.time()}
    updated["title"] = meta.get("title")  # 模拟保留逻辑
    write_meta(tmp_path, "test_sid", updated)

    final = read_meta(tmp_path, "test_sid")
    assert final is not None
    assert final["title"] == "persistent title"


@pytest.mark.asyncio
async def test_rename_no_args_lists_sessions(tmp_path: Path) -> None:
    """无参数时列出会话供选择。"""
    _write_session(tmp_path, "abc123", summary="session A")
    _write_session(tmp_path, "def456", summary="session B")
    ctx = _make_context(tmp_path)

    result = await rename_handler("", ctx)

    message = result.message or ""
    assert "#1" in message
    assert "#2" in message
    assert result.refresh_state is False


@pytest.mark.asyncio
async def test_rename_no_sessions(tmp_path: Path) -> None:
    """无已保存会话时返回提示。"""
    ctx = _make_context(tmp_path)

    result = await rename_handler("", ctx)

    assert result.message is not None
    assert "no" in result.message.lower() or "没有" in result.message


@pytest.mark.asyncio
async def test_rename_truncates_long_name(tmp_path: Path) -> None:
    """超过 80 字符的名称被截断。"""
    _write_session(tmp_path, "test_sid")
    ctx = _make_context(tmp_path)

    long_name = "a" * 100
    await rename_handler(long_name, ctx)

    meta = read_meta(tmp_path, "test_sid")
    assert meta is not None
    assert len(meta["title"]) == 80


@pytest.mark.asyncio
async def test_rename_strips_whitespace(tmp_path: Path) -> None:
    """首尾空白字符被 strip。"""
    _write_session(tmp_path, "test_sid")
    ctx = _make_context(tmp_path)

    await rename_handler("  trimmed name  ", ctx)

    meta = read_meta(tmp_path, "test_sid")
    assert meta is not None
    assert meta["title"] == "trimmed name"


@pytest.mark.asyncio
async def test_rename_multi_word_name(tmp_path: Path) -> None:
    """多词名称完整保留。"""
    _write_session(tmp_path, "test_sid")
    ctx = _make_context(tmp_path)

    await rename_handler("my cool session name", ctx)

    meta = read_meta(tmp_path, "test_sid")
    assert meta is not None
    assert meta["title"] == "my cool session name"
