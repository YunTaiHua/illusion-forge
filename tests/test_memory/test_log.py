"""记忆子代理活动日志工具测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from illusion_forge.memory.log import get_memory_logger, truncate


@pytest.fixture(autouse=True)
def reset_memory_loggers():
    """每个测试前后清理记忆日志器缓存（避免跨测试污染）。"""
    from illusion_forge.memory import log as log_mod

    log_mod._loggers.clear()
    yield
    log_mod._loggers.clear()


def test_truncate_short_text():
    assert truncate("hello world") == "hello world"


def test_truncate_long_text():
    long_text = " ".join(f"word-{i}" for i in range(200))
    result = truncate(long_text, limit=100)
    assert len(result) <= 104  # 100 + "..."
    assert result.endswith("...")


def test_truncate_single_line():
    assert truncate("a\nb\nc") == "a b c"


def test_memory_logger_writes_file(tmp_path: Path, monkeypatch):
    """日志器应写入 ~/.illusion/logs/memory_extract.log。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.config.paths import get_logs_dir

    logger = get_memory_logger("extract")
    logger.info("test activity line")
    for handler in logger.handlers:
        handler.flush()

    log_file = get_logs_dir() / "memory_extract.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "test activity line" in content


def test_memory_logger_cached(tmp_path: Path, monkeypatch):
    """同一 kind 的日志器应缓存复用（不重复添加 handler）。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))

    logger1 = get_memory_logger("dream")
    logger2 = get_memory_logger("dream")
    assert logger1 is logger2
    assert len(logger1.handlers) == 1


def test_memory_logger_propagate_false(tmp_path: Path, monkeypatch):
    """propagate=False：不传播到根 logger（避免控制台刷屏）。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))

    logger = get_memory_logger("extract")
    assert logger.propagate is False


def test_memory_logger_cleans_old_logs(tmp_path: Path, monkeypatch):
    """创建日志器时应清理超过保留天数的旧记忆活动日志。"""
    import os
    import time as _time

    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))

    from illusion_forge.config.paths import get_logs_dir

    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    # 旧日志（10 天前）
    old_log = logs_dir / "memory_dream.log"
    old_log.write_text("old", encoding="utf-8")
    old = _time.time() - 10 * 24 * 3600
    os.utime(old_log, (old, old))

    get_memory_logger("dream")

    # 旧文件（10 天前）已被清理；同名新文件由 handler 重新创建（mtime 为现在）
    new_log = logs_dir / "memory_dream.log"
    assert new_log.exists()
    assert new_log.stat().st_mtime > old + 5 * 24 * 3600  # 不是 10 天前的旧文件
