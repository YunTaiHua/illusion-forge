"""Shared test fixtures."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """全局隔离数据与配置目录，防止测试污染真实 ~/.illusion/ 目录。

    同时隔离 ILLUSION_DATA_DIR（数据目录）和 ILLUSION_CONFIG_DIR（配置目录，
    memory 目录迁至此处），所有测试自动应用此 fixture，无需手动设置。
    """
    from illusion_forge.daemon_ipc import DaemonType
    import illusion_forge.daemon_ipc as daemon_ipc

    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    if os.name == "nt":
        channel_pipe_name = f"\\\\.\\pipe\\illusion_test_channel_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    else:
        channel_pipe_name = str(tmp_path / f"channel_test_{uuid.uuid4().hex[:8]}.sock")

    original_default_pipe_name = daemon_ipc._default_pipe_name

    def _isolated_default_pipe_name(daemon_type: DaemonType) -> str:
        if daemon_type == DaemonType.CHANNEL:
            return channel_pipe_name
        return original_default_pipe_name(daemon_type)

    monkeypatch.setattr(daemon_ipc, "_default_pipe_name", _isolated_default_pipe_name)
