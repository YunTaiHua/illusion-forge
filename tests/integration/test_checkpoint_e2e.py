"""Checkpoint 端到端集成测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from illusion_forge.engine.messages import ConversationMessage
from illusion_forge.services.checkpoint_store import CheckpointStore


@pytest.mark.asyncio
async def test_cross_restart_rewind(tmp_path: Path) -> None:
    """跨重启 rewind：多轮对话 → 重启 → rewind → 状态正确。"""
    session_dir = tmp_path / "sess-abc"
    session_dir.mkdir()
    # 模拟第一轮（写入）
    store1 = CheckpointStore(session_dir, "abc")
    await store1.append_checkpoint()  # id=0
    await store1.append_message(ConversationMessage.from_user_text("turn0"))
    await store1.append_usage(100, 5, cache_read_input_tokens=1000)
    await store1.append_checkpoint()  # id=1
    await store1.append_message(ConversationMessage.from_user_text("turn1"))
    await store1.append_usage(200, 10, cache_read_input_tokens=2000)

    # 模拟重启（新 store 实例从同一文件 restore）
    store2 = CheckpointStore(session_dir, "abc")
    result = await store2.restore()
    assert store2.next_checkpoint_id == 2
    assert len(result.messages) == 2
    assert result.usage_input == 200
    assert result.usage_cache_read == 2000

    # rewind 到 id=1 之前
    result = await store2.rewind_to(1)
    assert result.checkpoint_count == 1
    assert len(result.messages) == 1
    assert result.messages[0].text == "turn0"
    assert result.usage_input == 100
    assert store2.next_checkpoint_id == 1


@pytest.mark.asyncio
async def test_resume_after_rewind(tmp_path: Path) -> None:
    """rewind 后 resume 不应恢复到 rewind 前。"""
    session_dir = tmp_path / "sess-abc"
    session_dir.mkdir()
    store = CheckpointStore(session_dir, "abc")
    await store.append_checkpoint()
    await store.append_message(ConversationMessage.from_user_text("msg1"))
    await store.append_usage(100, 5)
    await store.append_checkpoint()
    await store.append_message(ConversationMessage.from_user_text("msg2"))
    await store.append_usage(200, 10)

    # rewind 1 turn
    await store.rewind_to(1)

    # 新 store 从文件 restore
    store2 = CheckpointStore(session_dir, "abc")
    result = await store2.restore()
    assert len(result.messages) == 1
    assert result.messages[0].text == "msg1"
    assert result.usage_input == 100
