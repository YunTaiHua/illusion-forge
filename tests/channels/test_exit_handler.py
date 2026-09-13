"""exit_handler 废弃后的 noop 行为测试

handle_daemon_exit_on_interrupt 已废弃，保留壳函数返回 noop。
验证调用时不抛异常，不执行任何操作。

旧方案的测试场景（已全部移除）：
- is_channel_daemon_running 返回 True/False
- _confirm_exit 输入 y/Y/yes/回车
- _confirm_exit 二次 Ctrl+C (KeyboardInterrupt)
- _confirm_exit EOF (非 TTY)
- stop_channel_daemon_by_pid 调用追踪
- OSError 防御性兜底

IPC 连接监控机制替代了原有的退出确认流程。
"""
from __future__ import annotations


def test_handle_daemon_exit_on_interrupt_is_noop():
    """handle_daemon_exit_on_interrupt 应为 noop，不抛异常"""
    from illusion_forge.channels.exit_handler import handle_daemon_exit_on_interrupt

    # 不应抛出异常，不执行任何操作
    handle_daemon_exit_on_interrupt()


def test_handle_daemon_exit_on_interrupt_returns_none():
    """handle_daemon_exit_on_interrupt 返回 None"""
    from illusion_forge.channels.exit_handler import handle_daemon_exit_on_interrupt

    result = handle_daemon_exit_on_interrupt()
    assert result is None


def test_confirm_exit_function_removed():
    """_confirm_exit 私有函数应已删除"""
    from illusion_forge.channels import exit_handler

    # _confirm_exit 应不存在
    assert not hasattr(exit_handler, "_confirm_exit")


def test_exit_handler_no_dangerous_imports():
    """exit_handler 不应再导入 stop_channel_daemon_by_pid / is_channel_daemon_running"""
    import inspect

    from illusion_forge.channels import exit_handler

    source = inspect.getsource(exit_handler)
    # 不应包含对 stop_channel_daemon_by_pid / is_channel_daemon_running / load_channels_config 的调用
    assert "stop_channel_daemon_by_pid" not in source, (
        "exit_handler 不应再调用 stop_channel_daemon_by_pid"
    )
    assert "is_channel_daemon_running" not in source, (
        "exit_handler 不应再调用 is_channel_daemon_running"
    )
    assert "load_channels_config" not in source, (
        "exit_handler 不应再调用 load_channels_config"
    )
    assert "input(" not in source, (
        "exit_handler 不应再有 input() 调用（确认提示已移除）"
    )
