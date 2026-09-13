"""bug 修复验证测试：Ctrl+X 任务终止（Bug 2）。

原文件还包含 Bug 1（textual_app 权限模态框死锁）回归测试，
但 textual_app.py 已作为死代码删除，故仅保留对 agent_executor 的回归测试。

验证的 bug：
1. Bug 2: agent_executor finally 块漏 cancel query_task，外层 cancel 传播时
   query_task 泄漏，工具继续运行，Ctrl+X 无法终止任务。修复：finally 中显式 cancel query_task。
"""
from __future__ import annotations

import inspect

from illusion_forge.swarm.agent_executor import run_agent_in_process


def test_agent_executor_finally_cancels_query_task():
    """agent_executor finally 块应显式 cancel query_task，避免 Ctrl+X 时泄漏。"""
    src = inspect.getsource(run_agent_in_process)
    # 定位 finally 块中的 query_task cancel 逻辑
    assert "if not query_task.done()" in src, "finally 块应检查 query_task.done()"
    assert "query_task.cancel()" in src, "finally 块应 cancel query_task"


def test_agent_executor_cancels_query_task_on_outer_cancel():
    """agent_executor 在外层 cancel 传播时应 cancel query_task（回归测试）。

    Bug 2 回归测试：当 _stop_active_line 调用 task.cancel() 时，
    await asyncio.wait 抛 CancelledError，finally 块应 cancel query_task。
    """
    # 验证 finally 块的源码结构：query_task cancel 在 message_task 之后、helpers 之前
    src = inspect.getsource(run_agent_in_process)
    finally_idx = src.index("finally:")
    # 找到 finally 块内的关键代码顺序
    msg_shutdown_idx = src.index("ctx.message_queue.shutdown()", finally_idx)
    query_cancel_idx = src.index("if not query_task.done()", finally_idx)
    helpers_idx = src.index("pending_helpers", finally_idx)

    assert msg_shutdown_idx < query_cancel_idx < helpers_idx, (
        "finally 块顺序应为：message_queue.shutdown → query_task cancel → helpers cancel"
    )
