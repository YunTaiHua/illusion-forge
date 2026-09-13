"""渠道守护进程废弃函数测试

验证 kill_channel_daemon / stop_channel_daemon_by_pid 标记废弃后：
1. 调用时发出 DeprecationWarning
2. 不执行任何操作（noop）
3. 返回值符合废弃后的契约
"""
from __future__ import annotations

import warnings

import pytest


def test_kill_channel_daemon_emits_deprecation_warning():
    """kill_channel_daemon 调用时发出 DeprecationWarning"""
    from illusion_forge.channels import kill_channel_daemon

    with pytest.warns(DeprecationWarning):
        kill_channel_daemon(None)  # proc=None


def test_kill_channel_daemon_returns_none():
    """kill_channel_daemon 废弃后返回 None（noop）"""
    from illusion_forge.channels import kill_channel_daemon

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = kill_channel_daemon(None)
    assert result is None


def test_stop_channel_daemon_by_pid_emits_deprecation_warning():
    """stop_channel_daemon_by_pid 调用时发出 DeprecationWarning"""
    from illusion_forge.channels import stop_channel_daemon_by_pid

    with pytest.warns(DeprecationWarning):
        stop_channel_daemon_by_pid()


def test_stop_channel_daemon_by_pid_returns_false():
    """stop_channel_daemon_by_pid 废弃后返回 False"""
    from illusion_forge.channels import stop_channel_daemon_by_pid

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = stop_channel_daemon_by_pid()
    assert result is False


def test_is_channel_daemon_running_still_callable():
    """is_channel_daemon_running 保留向后兼容，仍可调用"""
    from illusion_forge.channels import is_channel_daemon_running

    # 不应抛异常（可能返回 True 或 False，取决于实际是否有守护进程）
    result = is_channel_daemon_running()
    assert isinstance(result, bool)
