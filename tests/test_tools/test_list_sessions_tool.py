"""list_sessions 工具测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from illusion_forge.services.session_storage import session_dir_for
from illusion_forge.tools.base import ToolExecutionContext
from illusion_forge.tools.list_sessions_tool import ListSessionsTool


def _write_session_meta(cwd: Path, session_id: str, summary: str, message_count: int) -> None:
    """写入一个会话的 meta.json（模拟已保存会话）。"""
    session_dir = session_dir_for(cwd, session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "meta.json").write_text(json.dumps({
        "session_id": session_id,
        "summary": summary,
        "message_count": message_count,
        "turn_count": 1,
        "created_at": 1700000000,
        "updated_at": 1700000100,
    }, ensure_ascii=False), encoding="utf-8")


@pytest.fixture(autouse=True)
def _tmp_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """重定向配置/会话目录到临时目录（cwd 由各测试自行指定）。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))


@pytest.mark.asyncio
async def test_no_sessions(tmp_path: Path) -> None:
    """无会话时返回提示（仍显示当前会话）。"""
    tool = ListSessionsTool()
    ctx = ToolExecutionContext(cwd=tmp_path, metadata={"session_id": "s1"})
    result = await tool.execute(tool.input_model(limit=20), ctx)
    assert "No saved sessions" in result.output
    assert "s1" in result.output


@pytest.mark.asyncio
async def test_lists_sessions_with_current_marker(tmp_path: Path) -> None:
    """列出会话并标注当前会话。"""
    _write_session_meta(tmp_path, "sess_a", "第一个会话", 5)
    _write_session_meta(tmp_path, "sess_b", "第二个会话", 3)
    tool = ListSessionsTool()
    ctx = ToolExecutionContext(cwd=tmp_path, metadata={"session_id": "sess_b"})
    result = await tool.execute(tool.input_model(limit=20), ctx)
    output = result.output
    assert "Current session: sess_b" in output
    assert "sess_a" in output
    assert "第一个会话" in output
    assert "[current]" in output
    # 仅 sess_b 有 current 标注
    assert output.count("[current]") == 1


@pytest.mark.asyncio
async def test_limit_applies(tmp_path: Path) -> None:
    """limit 参数生效。"""
    for i in range(5):
        _write_session_meta(tmp_path, f"sess_{i}", f"会话{i}", 1)
    tool = ListSessionsTool()
    ctx = ToolExecutionContext(cwd=tmp_path, metadata={})
    result = await tool.execute(tool.input_model(limit=3), ctx)
    assert "Sessions (3)" in result.output


@pytest.mark.asyncio
async def test_is_read_only(tmp_path: Path) -> None:
    """list_sessions 为只读工具。"""
    tool = ListSessionsTool()
    assert tool.is_read_only(tool.input_model(limit=10)) is True
