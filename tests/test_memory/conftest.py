"""tests/test_memory 共享 fixture：所有记忆测试隔离真实用户环境。

将 ILLUSION_CONFIG_DIR / ILLUSION_DATA_DIR / ILLUSION_LOGS_DIR
指向 pytest 临时目录，确保：
    - 记忆文件创建/删除不触碰真实 ~/.illusion
    - 日志文件写入/周期清理不触碰真实 ~/.illusion/logs
    - 任何路径解析都基于临时目录（配合 get_xx_dir 的环境变量覆盖）
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_illusion_env(tmp_path, monkeypatch):
    """每个记忆测试自动隔离配置/数据/日志目录。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ILLUSION_LOGS_DIR", str(tmp_path / "logs"))
    yield
