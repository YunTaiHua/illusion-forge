"""QueryEngine 与 CheckpointStore 集成测试。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from illusion_forge.engine.messages import ConversationMessage
from illusion_forge.engine.query_engine import QueryEngine


def _make_engine(tmp_path: Path) -> QueryEngine:
    """构造测试用 QueryEngine（不调用真实 API）。"""
    return QueryEngine(
        api_client=MagicMock(),
        tool_registry=MagicMock(),
        permission_checker=MagicMock(),
        cwd=tmp_path,
        model="test-model",
        system_prompt="sys",
    )


@pytest.mark.asyncio
async def test_submit_message_appends_checkpoint(tmp_path: Path, monkeypatch) -> None:
    """submit_message 入口 append checkpoint + user message。"""
    from illusion_forge.services.checkpoint_store import CheckpointStore

    engine = _make_engine(tmp_path)
    store = CheckpointStore(tmp_path / "sess", "abc")
    engine.set_checkpoint_store(store)
    engine.set_system_prompt("sys")

    # mock run_query 返回空事件流（使用 monkeypatch 自动还原，避免污染后续测试）
    import illusion_forge.engine.query_engine as qe_mod
    async def _fake_run_query(ctx, msgs):
        if False:
            yield  # 让函数成为 async generator（不 yield 任何东西）
    monkeypatch.setattr(qe_mod, "run_query", _fake_run_query)

    async for _ in engine.submit_message("hello"):
        pass

    result = await store.restore()
    assert result.checkpoint_count == 1
    assert len(result.messages) >= 1
    assert result.messages[0].text == "hello"


@pytest.mark.asyncio
async def test_submit_message_persists_assistant_and_tool_messages(
    tmp_path: Path, monkeypatch
) -> None:
    """run_query 内部 append 的 assistant/tool 消息必须持久化到 CheckpointStore。

    回归测试：修复前 submit_message 只持久化 user message，run_query 内部
    append 的 assistant 回复和 tool 结果消息丢失，导致 resume 后对话历史缺失。
    """
    from illusion_forge.services.checkpoint_store import CheckpointStore

    engine = _make_engine(tmp_path)
    store = CheckpointStore(tmp_path / "sess", "abc")
    engine.set_checkpoint_store(store)
    engine.set_system_prompt("sys")

    # mock run_query：模拟内部 append assistant + tool result 消息
    import illusion_forge.engine.query_engine as qe_mod
    from illusion_forge.engine.messages import TextBlock
    from illusion_forge.engine.stream_events import AssistantTurnComplete
    from illusion_forge.api.usage import UsageSnapshot

    async def _fake_run_query(ctx, msgs):
        # 模拟 query.py 内部行为：append assistant 消息到 msgs（即 self._messages）
        assistant_msg = ConversationMessage(
            role="assistant",
            content=[TextBlock(type="text", text="你好！我是助手。")],
        )
        msgs.append(assistant_msg)
        # 模拟 append tool result user 消息
        tool_result_msg = ConversationMessage(
            role="user",
            content=[TextBlock(type="text", text="[tool_result] ok")],
        )
        msgs.append(tool_result_msg)
        yield AssistantTurnComplete(message=assistant_msg, usage=None), None

    monkeypatch.setattr(qe_mod, "run_query", _fake_run_query)

    async for _ in engine.submit_message("你好"):
        pass

    result = await store.restore()
    # 应该有 3 条消息：user(你好) + assistant(回复) + user(tool_result)
    assert len(result.messages) == 3
    assert result.messages[0].role == "user"
    assert result.messages[0].text == "你好"
    assert result.messages[1].role == "assistant"
    assert result.messages[1].text == "你好！我是助手。"
    assert result.messages[2].role == "user"
    assert result.messages[2].text == "[tool_result] ok"


@pytest.mark.asyncio
async def test_continue_pending_persists_assistant_messages(
    tmp_path: Path, monkeypatch
) -> None:
    """continue_pending 同样必须持久化 run_query 内部 append 的消息。"""
    from illusion_forge.services.checkpoint_store import CheckpointStore
    from illusion_forge.engine.messages import TextBlock
    from illusion_forge.engine.stream_events import AssistantTurnComplete

    engine = _make_engine(tmp_path)
    store = CheckpointStore(tmp_path / "sess", "abc")
    engine.set_checkpoint_store(store)
    engine.set_system_prompt("sys")

    # 预置一条待续的 user message（含 tool_result）模拟中断恢复场景
    engine._messages.append(ConversationMessage.from_user_text("继续"))
    await store.append_message(engine._messages[-1])

    import illusion_forge.engine.query_engine as qe_mod

    async def _fake_run_query(ctx, msgs):
        assistant_msg = ConversationMessage(
            role="assistant",
            content=[TextBlock(type="text", text="已继续执行")],
        )
        msgs.append(assistant_msg)
        yield AssistantTurnComplete(message=assistant_msg, usage=None), None

    monkeypatch.setattr(qe_mod, "run_query", _fake_run_query)

    async for _ in engine.continue_pending():
        pass

    result = await store.restore()
    # 应该有 2 条消息：user(继续) + assistant(已继续执行)
    assert len(result.messages) == 2
    assert result.messages[0].role == "user"
    assert result.messages[0].text == "继续"
    assert result.messages[1].role == "assistant"
    assert result.messages[1].text == "已继续执行"


def test_full_reset_clears_all_state(tmp_path: Path) -> None:
    """full_reset 清空所有状态。"""
    engine = _make_engine(tmp_path)
    engine._messages.append(ConversationMessage.from_user_text("x"))
    engine._session_id = "old"
    engine.full_reset()
    assert engine.messages == []
    assert engine._session_id == ""
    assert engine._checkpoint_store is None


def test_set_session_id(tmp_path: Path) -> None:
    """set_session_id 更新内部 session_id。"""
    engine = _make_engine(tmp_path)
    engine.set_session_id("new_sid")
    assert engine._session_id == "new_sid"


def test_attach_session_derives_session_id_and_resets_file_history(tmp_path: Path) -> None:
    """attach_session 原子绑定：session_id 由 store 派生、file_history 重置、tool_metadata 同步。

    回归防护：若 attach_session 漏同步任一（如沿用旧 session_id、不重置
    file_history、不更新 tool_metadata），会话切换后文件会散落到旧目录，
    工具上下文也会拿到错误的 session_id。
    """
    from illusion_forge.services.checkpoint_store import CheckpointStore
    from illusion_forge.services.file_history import FileHistoryState

    engine = _make_engine(tmp_path)
    # 预置"旧会话"状态：旧 store + 已加载的 file_history + 旧 tool_metadata
    old_store = CheckpointStore(tmp_path / "old", "old-sid")
    engine.attach_session(old_store)
    engine._file_history = FileHistoryState(
        session_id="old-sid", cwd=str(tmp_path), session_dir=old_store.session_dir
    )
    assert engine.tool_metadata["session_id"] == "old-sid"

    new_store = CheckpointStore(tmp_path / "new", "new-sid")
    engine.attach_session(new_store)

    assert engine._session_id == "new-sid"
    assert engine._file_history is None
    assert engine.checkpoint_store is new_store
    assert engine.tool_metadata["session_id"] == "new-sid"


@pytest.mark.asyncio
async def test_submit_message_persists_files_in_store_session_dir(
    tmp_path: Path, monkeypatch
) -> None:
    """会话切换后 submit_message 必须把 context.jsonl / file_history.json 写入 store.session_dir。

    回归防护（核心不变量）：context.jsonl 与 file_history.json 必须同目录。
    若 file_history 按旧 session_id / 旧目录计算路径，或 attach_session
    后未重置旧 file_history，两者会散落不同目录，resume/rewind 失效。
    """
    import json

    from illusion_forge.services.checkpoint_store import CheckpointStore

    engine = _make_engine(tmp_path)
    store = CheckpointStore(tmp_path / "sess", "abc")
    engine.attach_session(store)
    engine.set_system_prompt("sys")

    # mock run_query 返回空事件流
    import illusion_forge.engine.query_engine as qe_mod
    async def _fake_run_query(ctx, msgs):
        if False:
            yield
    monkeypatch.setattr(qe_mod, "run_query", _fake_run_query)

    async for _ in engine.submit_message("hello"):
        pass

    # context.jsonl 与 file_history.json 必须落在同一会话目录
    assert (store.session_dir / "context.jsonl").exists()
    assert (store.session_dir / "file_history.json").exists()
    fh = json.loads(
        (store.session_dir / "file_history.json").read_text(encoding="utf-8")
    )
    assert fh["session_id"] == "abc"


def test_load_file_history_reads_from_store_dir(tmp_path: Path) -> None:
    """load_file_history 必须从 checkpoint_store.session_dir 读取（/resume 路径）。

    回归防护：若按 cwd+session_id 重算路径且与 store 目录不一致，
    会加载不到（保持 None）或加载到旧会话文件，rewind 失效。
    """
    from illusion_forge.services.checkpoint_store import CheckpointStore
    from illusion_forge.services.file_history import FileHistoryState
    from illusion_forge.services.file_history import save as fh_save

    engine = _make_engine(tmp_path)
    store = CheckpointStore(tmp_path / "sess", "abc")
    engine.attach_session(store)

    # 预置 file_history.json 到 store.session_dir（模拟 /resume 前的磁盘状态）
    fh_save(
        FileHistoryState(
            session_id="abc", cwd=str(tmp_path), session_dir=store.session_dir
        )
    )

    engine.load_file_history(checkpoint_count=store.next_checkpoint_id)

    assert engine._file_history is not None
    assert engine._file_history.session_id == "abc"
    assert engine._file_history.session_dir == store.session_dir
