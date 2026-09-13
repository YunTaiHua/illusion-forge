"""StderrRedirector 单元测试。

注意：本测试套件修改 root logger 配置，与 pytest 的 logging plugin
（caplog fixture）冲突。运行时需禁用 logging plugin：

    pytest tests/test_utils/test_stderr_redirect.py -p no:logging
"""

from __future__ import annotations

import logging
import os
import threading

from illusion_forge.utils.stderr_redirect import StderrRedirector


def test_install_uninstall_roundtrip():
    """install 后 stderr 被重定向，uninstall 后恢复。"""
    redirector = StderrRedirector(logger_name="test_stderr", level=logging.ERROR)
    redirector.install()
    try:
        # install 后写 stderr 应该不直接输出到原 stderr
        os.write(2, b"redirected line\n")
    finally:
        redirector.uninstall()


def test_uninstall_is_idempotent():
    """uninstall 可重复调用不报错。"""
    redirector = StderrRedirector(logger_name="test_stderr")
    redirector.install()
    redirector.uninstall()
    redirector.uninstall()  # 幂等


def test_install_is_idempotent():
    """install 可重复调用不报错。"""
    redirector = StderrRedirector(logger_name="test_stderr")
    redirector.install()
    redirector.install()  # 幂等
    redirector.uninstall()


def test_open_original_stderr_handle():
    """install 后仍可获取原始 stderr 句柄。"""
    redirector = StderrRedirector(logger_name="test_stderr")
    redirector.install()
    try:
        handle = redirector.open_original_stderr_handle()
        assert handle is not None
        handle.close()
    finally:
        redirector.uninstall()


def test_stderr_logger_does_not_propagate_to_root():
    """illusion_forge.stderr logger 必须禁止传播到 root。

    回归测试：若 propagate=True，daemon 通过 root 写 fd 2（管道）会形成死锁。
    """
    redirector = StderrRedirector(logger_name="test_stderr_no_prop", level=logging.ERROR)
    redirector.install()
    try:
        logger = redirector._logger
        assert logger.propagate is False, (
            "illusion_forge.stderr logger 必须 propagate=False，否则会通过 root 写 fd 2 形成死锁"
        )
    finally:
        redirector.uninstall()


def test_root_logger_handlers_replaced_to_original_fd():
    """install 后 root logger 的 StreamHandler 必须写原始 fd，而非 fd 2（管道）。"""
    redirector = StderrRedirector(logger_name="test_stderr_root", level=logging.ERROR)
    redirector.install()
    try:
        root_logger = logging.getLogger()
        # lastResort 必须被禁用，避免写 fd 2
        assert logging.lastResort is None, "lastResort 必须禁用，否则会写 fd 2（管道）"
        # root 必须有 handler 写原始 fd
        assert len(root_logger.handlers) > 0, "root logger 必须有 handler"
    finally:
        redirector.uninstall()


def test_root_logger_restored_after_uninstall():
    """uninstall 后 root logger 配置必须恢复。"""
    redirector = StderrRedirector(logger_name="test_stderr_restore", level=logging.ERROR)
    redirector.install()
    redirector.uninstall()

    # uninstall 后 lastResort 应恢复
    assert logging.lastResort is not None, "uninstall 后 lastResort 应恢复"


def test_no_deadlock_when_main_thread_logs_while_stderr_redirect_active():
    """主线程在 stderr 重定向期间调用 logging 不应死锁。

    回归测试：复现后台 agent 卡住场景——主线程调用 logger.warning 时，
    若 root handler 写 fd 2（管道）阻塞，会形成死锁。
    修复后 root handler 写原始 fd，daemon 用 os.write 不持锁，不死锁。
    """
    redirector = StderrRedirector(logger_name="test_stderr_deadlock", level=logging.WARNING)
    redirector.install()
    try:
        # 触发 daemon 线程读管道：写大量数据到 fd 2
        os.write(2, b"stderr line 1\nstderr line 2\n" * 100)

        # 主线程并发调用 logging，若死锁会超时
        done_event = threading.Event()
        error_box: list[Exception] = []

        def _log_in_thread():
            try:
                test_logger = logging.getLogger("test.deadlock.check")
                for _ in range(50):
                    test_logger.warning("main thread logging while stderr redirected")
                done_event.set()
            except (OSError, RuntimeError) as exc:
                error_box.append(exc)
                done_event.set()

        t = threading.Thread(target=_log_in_thread, daemon=True)
        t.start()
        # 3s 足够：死锁时永不完成，正常时毫秒级完成
        assert done_event.wait(timeout=3.0), (
            "主线程 logging 死锁：root handler 写管道阻塞，主线程等 lock 超时"
        )
        t.join(timeout=1.0)
        assert not error_box, f"logging 调用异常: {error_box}"
    finally:
        redirector.uninstall()
