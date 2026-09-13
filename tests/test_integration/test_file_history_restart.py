"""file_history 跨重启集成测试。"""
from __future__ import annotations

from pathlib import Path

from illusion_forge.services.file_history import (
    FileHistoryState,
    load,
    make_snapshot,
    rewind_to,
    track_edit,
)


def test_restart_then_rewind_to_restores_file(tmp_path: Path) -> None:
    """模拟重启：engine1 修改文件 → 保存 → 新 state load + rewind → 文件恢复。"""
    cwd = str(tmp_path)
    session_id = "abc123"
    target = tmp_path / "file.py"

    # === engine1 阶段 ===
    state1 = FileHistoryState(session_id=session_id, cwd=cwd)
    make_snapshot(state1, "1", checkpoint_id=0)
    # 模拟工具修改文件前 track_edit（备份原内容）
    target.write_text("original", encoding="utf-8")
    track_edit(state1, str(target))
    # 模拟工具修改文件
    target.write_text("modified", encoding="utf-8")

    # === 重启：新建 state2，从磁盘 load ===
    state2 = load(cwd, session_id, checkpoint_count=1)
    assert state2 is not None
    assert len(state2.snapshots) == 1
    assert state2.snapshots[0].checkpoint_id == 0

    # === rewind_to: 回退到 cp_id=0 之前 ===
    target_index = max(0, len(state2.snapshots) - 1)
    target_cp_id = state2.snapshots[target_index].checkpoint_id
    changed = rewind_to(state2, target_cp_id)
    assert str(target.resolve()) in changed
    assert target.read_text(encoding="utf-8") == "original"


def test_restart_rewind_partial_then_full_no_misalignment(tmp_path: Path) -> None:
    """跨重启：部分回退后再整体回退，checkpoint_id 定位不错位。"""
    cwd = str(tmp_path)
    session_id = "abc123"
    target = tmp_path / "file.py"

    # === engine1: 3 轮 ===
    state1 = FileHistoryState(session_id=session_id, cwd=cwd)

    make_snapshot(state1, "1", checkpoint_id=0)
    target.write_text("v0", encoding="utf-8")
    track_edit(state1, str(target))
    target.write_text("v1", encoding="utf-8")

    make_snapshot(state1, "2", checkpoint_id=1)
    track_edit(state1, str(target))
    target.write_text("v2", encoding="utf-8")

    make_snapshot(state1, "3", checkpoint_id=2)
    track_edit(state1, str(target))
    target.write_text("v3", encoding="utf-8")

    # === 重启 ===
    state2 = load(cwd, session_id, checkpoint_count=3)
    assert state2 is not None
    assert len(state2.snapshots) == 3

    # === 部分回退: 移除 cp_id=2 的快照 ===
    target_index = max(0, len(state2.snapshots) - 1)
    target_cp_id = state2.snapshots[target_index].checkpoint_id
    assert target_cp_id == 2
    rewind_to(state2, target_cp_id)
    assert len(state2.snapshots) == 2
    assert [s.checkpoint_id for s in state2.snapshots] == [0, 1]
    # 文件恢复到 v2
    assert target.read_text(encoding="utf-8") == "v2"

    # === 发新消息: cp=3, 新快照 cp_id=3 ===
    make_snapshot(state2, "4", checkpoint_id=3)
    track_edit(state2, str(target))
    target.write_text("v3_new", encoding="utf-8")

    # === 重启 ===
    state3 = load(cwd, session_id, checkpoint_count=4)
    assert state3 is not None
    assert [s.checkpoint_id for s in state3.snapshots] == [0, 1, 3]

    # === 整体回退: target_cp = 4 - 1 = 3 ===
    rewind_to(state3, 3)
    assert [s.checkpoint_id for s in state3.snapshots] == [0, 1]
    # 文件恢复到 v2（v3_new 被撤销）
    assert target.read_text(encoding="utf-8") == "v2"

    # === 再次整体回退: target_cp = 3 - 1 = 2 ===
    # 无 cp_id >= 2 的快照（S2 已被部分回退移除），不恢复文件
    changed = rewind_to(state3, 2)
    assert changed == []
    assert [s.checkpoint_id for s in state3.snapshots] == [0, 1]
    # 文件仍为 v2
    assert target.read_text(encoding="utf-8") == "v2"


def test_restart_after_rewind_persists(tmp_path: Path) -> None:
    """rewind 后重启，状态应反映 rewind 后的快照列表。"""
    cwd = str(tmp_path)
    session_id = "abc123"

    state1 = FileHistoryState(session_id=session_id, cwd=cwd)
    make_snapshot(state1, "1", checkpoint_id=0)
    make_snapshot(state1, "2", checkpoint_id=1)
    make_snapshot(state1, "3", checkpoint_id=2)

    # rewind 1
    rewind_to(state1, 2)
    assert len(state1.snapshots) == 2

    # 重启
    state2 = load(cwd, session_id, checkpoint_count=2)
    assert state2 is not None
    assert len(state2.snapshots) == 2
    assert [s.checkpoint_id for s in state2.snapshots] == [0, 1]
