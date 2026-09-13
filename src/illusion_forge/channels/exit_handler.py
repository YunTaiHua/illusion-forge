"""共享退出处理器（已废弃）
========================

此模块已废弃，保留壳函数向后兼容。

新方案采用 IPC 连接数管理：
    - 主程序退出时关闭 IPC 连接（DaemonClient.close()）
    - 守护进程检测到连接归零后自动退出
    - 不再弹确认提示，不再处理 Y/回车/二次 Ctrl+C/EOF 等输入

旧方案行为（已废弃）：
    - 检查守护进程状态 → 弹确认提示
    - y/Y/yes/空回车 → 停止守护进程
    - 二次 Ctrl+C → 停止守护进程
    - 其他输入 → 不停止
    - EOF（非 TTY）→ 不停止

函数说明：
    - handle_daemon_exit_on_interrupt: 已废弃，noop（保留向后兼容）

使用示例（已不推荐）：
    >>> from illusion_forge.channels.exit_handler import handle_daemon_exit_on_interrupt
    >>> handle_daemon_exit_on_interrupt()  # noop，不执行任何操作
"""
from __future__ import annotations


def handle_daemon_exit_on_interrupt() -> None:
    """已废弃的退出处理器（noop）

    此函数保留向后兼容，不执行任何操作。
    新方案请使用 DaemonClient.close() 关闭 IPC 连接。

    旧方案的确认提示、Y/回车/二次 Ctrl+C/EOF 处理已全部移除。
    主程序退出时直接关闭 IPC 连接，守护进程通过连接数自管理决定是否退出。
    """
    return
