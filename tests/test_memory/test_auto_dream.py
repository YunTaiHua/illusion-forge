"""Auto Dream 记忆整合状态机测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from illusion_forge.memory.auto_dream import (
    DREAM_STATE_FILE,
    _load_dream_state,
    _now_iso,
    _save_dream_state,
)


def _make_memory_dir(tmp_path: Path) -> Path:
    memory_dir = tmp_path / "mem"
    memory_dir.mkdir()
    return memory_dir


def test_load_dream_state_missing(tmp_path: Path):
    memory_dir = _make_memory_dir(tmp_path)
    state = _load_dream_state(memory_dir)
    assert state == {"last_dream_at": None, "session_count": 0}


def test_save_and_load_dream_state(tmp_path: Path):
    memory_dir = _make_memory_dir(tmp_path)
    _save_dream_state(memory_dir, {"last_dream_at": _now_iso(), "session_count": 3})

    state = _load_dream_state(memory_dir)
    assert state["session_count"] == 3
    assert state["last_dream_at"] is not None


def test_load_dream_state_corrupted(tmp_path: Path):
    memory_dir = _make_memory_dir(tmp_path)
    (memory_dir / DREAM_STATE_FILE).write_text("{invalid json", encoding="utf-8")

    state = _load_dream_state(memory_dir)
    assert state == {"last_dream_at": None, "session_count": 0}


def test_load_dream_state_non_int_count(tmp_path: Path):
    memory_dir = _make_memory_dir(tmp_path)
    (memory_dir / DREAM_STATE_FILE).write_text(
        '{"last_dream_at": null, "session_count": "oops"}', encoding="utf-8"
    )

    state = _load_dream_state(memory_dir)
    assert state["session_count"] == 0


def test_dream_state_file_location(tmp_path: Path):
    """状态文件应位于记忆目录内。"""
    memory_dir = _make_memory_dir(tmp_path)
    _save_dream_state(memory_dir, {"last_dream_at": None, "session_count": 1})
    assert (memory_dir / DREAM_STATE_FILE).exists()


def test_session_count_increments_across_saves(tmp_path: Path):
    """会话计数应跨保存累积。"""
    memory_dir = _make_memory_dir(tmp_path)
    for _ in range(4):
        state = _load_dream_state(memory_dir)
        state["session_count"] = state.get("session_count", 0) + 1
        _save_dream_state(memory_dir, state)

    assert _load_dream_state(memory_dir)["session_count"] == 4


def test_iso_timestamp_parseable():
    parsed = datetime.fromisoformat(_now_iso())
    assert parsed.tzinfo is not None


def test_last_dream_at_preserved_after_reset(tmp_path: Path):
    """整合完成后应写入 last_dream_at 并重置会话计数。"""
    memory_dir = _make_memory_dir(tmp_path)
    _save_dream_state(memory_dir, {"last_dream_at": None, "session_count": 6})

    # 模拟整合完成
    state = _load_dream_state(memory_dir)
    state["last_dream_at"] = _now_iso()
    state["session_count"] = 0
    _save_dream_state(memory_dir, state)

    final = _load_dream_state(memory_dir)
    assert final["session_count"] == 0
    assert final["last_dream_at"] is not None


def test_time_elapsed_calculation(tmp_path: Path):
    """超过 24 小时应判定为可整合（模拟状态）。"""
    memory_dir = _make_memory_dir(tmp_path)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    _save_dream_state(memory_dir, {"last_dream_at": old_time, "session_count": 5})

    state = _load_dream_state(memory_dir)
    last = datetime.fromisoformat(state["last_dream_at"])
    hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    assert hours >= 24


# --- C2 守卫 / I5 文件锁测试 ---


class FakeDreamEngine:
    """最小引擎桩（可选子代理标记）。"""

    def __init__(self, cwd: str | Path, *, is_subagent: bool = False) -> None:
        self.cwd = str(cwd)
        self._is_memory_subagent = is_subagent


def test_record_session_start_subagent_guard(tmp_path: Path, monkeypatch):
    """C2: 提取/整合子代理不是真实会话，不得计数或触发整合。"""
    from illusion_forge.memory.auto_dream import record_session_start

    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))

    engine = FakeDreamEngine(tmp_path, is_subagent=True)
    assert record_session_start(engine) is False

    # 状态文件不应被创建（子代理不计入会话数）
    from illusion_forge.memory.paths import get_memory_dir_for_cwd

    assert not (get_memory_dir_for_cwd(engine.cwd) / ".dream_state.json").exists()


def test_record_session_start_auto_extract_disabled(tmp_path: Path, monkeypatch):
    """auto_extract=false（手动模式）时不得触发整合。"""
    import json

    from illusion_forge.memory.auto_dream import record_session_start

    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))

    # 写入 settings.json：memory.enabled=true 但 auto_extract=false
    from illusion_forge.config.paths import get_config_file_path

    settings_path = get_config_file_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"memory": {"enabled": True, "auto_extract": False}}),
        encoding="utf-8",
    )

    engine = FakeDreamEngine(tmp_path)
    assert record_session_start(engine) is False

    # 状态文件不应被创建（手动模式下不计数）
    from illusion_forge.memory.paths import get_memory_dir_for_cwd

    assert not (get_memory_dir_for_cwd(engine.cwd) / ".dream_state.json").exists()


def test_dream_lock_acquire_and_release(tmp_path: Path):
    """I5: 文件锁可获取/释放；持锁期间不可重复获取。"""
    from illusion_forge.memory.auto_dream import (
        _acquire_dream_lock,
        _release_dream_lock,
    )

    memory_dir = _make_memory_dir(tmp_path)
    assert _acquire_dream_lock(memory_dir) is True
    assert _acquire_dream_lock(memory_dir) is False  # 已持锁
    _release_dream_lock(memory_dir)
    assert _acquire_dream_lock(memory_dir) is True  # 释放后可再获取
    _release_dream_lock(memory_dir)


def test_dream_lock_stale_recovery(tmp_path: Path):
    """I5: 崩溃残留锁超过过期时间应自动清除。"""
    import time as _time

    from illusion_forge.memory.auto_dream import (
        DREAM_LOCK_FILE,
        DREAM_LOCK_STALE_SECONDS,
        _acquire_dream_lock,
        _release_dream_lock,
    )

    memory_dir = _make_memory_dir(tmp_path)
    lock_path = memory_dir / DREAM_LOCK_FILE
    lock_path.write_text("stale", encoding="utf-8")
    # 把 mtime 改成很久以前
    old = _time.time() - DREAM_LOCK_STALE_SECONDS - 100
    import os

    os.utime(lock_path, (old, old))

    assert _acquire_dream_lock(memory_dir) is True
    _release_dream_lock(memory_dir)
