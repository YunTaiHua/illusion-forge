"""
stderr 重定向模块
=================

本模块提供 fd 级 stderr 重定向，将 C 扩展和 Python warnings 直接写 fd 2 的
输出捕获到 logger，避免污染标准输出流。

主要功能：
    - StderrRedirector: 通过 os.dup2 劫持 fd 2，daemon 线程逐行读取并交给 logger

类说明：
    - StderrRedirector: stderr 重定向器，支持 install/uninstall 生命周期
"""

from __future__ import annotations

import codecs
import contextlib
import locale
import logging
import os
import sys
import threading
from collections.abc import Iterator
from typing import IO


@contextlib.contextmanager
def _open_fd_stream(fd: int, encoding: str) -> Iterator[IO[str]]:
    """打开 fd 的 text stream 并用 with 管理生命周期，供 ExitStack 使用。"""
    with open(
        fd,
        "w",
        encoding=encoding,
        errors="replace",
        closefd=False,
        buffering=1,  # 行缓冲
    ) as stream:
        yield stream


class StderrRedirector:
    """stderr fd 级重定向器。

    通过 os.dup2 将 fd 2 重定向到管道写端，daemon 线程从管道读端逐行读取
    并直接 os.write 到原始 stderr fd。

    死锁防护：daemon 线程必须绕过 logging 模块。若用 logger.log()，
    独立 handler emit 失败会触发 handleError → 写 sys.stderr（fd 2，已重定向
    到管道）→ 管道写阻塞（daemon 持锁）→ 主线程等 lock → 死锁。

    Attributes:
        logger_name: logging 模块的 logger 名称（仅用于 propagate=False）
        level: 日志级别（保留兼容，实际未使用）
    """

    def __init__(self, logger_name: str = "illusion_forge.stderr", level: int = logging.ERROR) -> None:
        self._logger = logging.getLogger(logger_name)
        # 阻止向 root logger 传播：避免 daemon 通过 root 写 fd 2 形成死锁
        self._logger.propagate = False
        self._level = level
        self._encoding: str | None = None
        self._installed = False
        self._lock = threading.Lock()
        self._original_fd: int | None = None
        self._read_fd: int | None = None
        self._thread: threading.Thread | None = None
        # 保存 install 前的 root handler 配置，uninstall 时恢复
        self._saved_root_handlers: list[logging.Handler] | None = None
        self._saved_root_level: int | None = None
        # 保存每个 handler 的原始 stream，uninstall 时恢复以兼容 pytest logging plugin
        self._saved_streams: dict[int, object] = {}
        # 管理 install 中打开的原始 fd 副本 stream 的生命周期
        self._stream_stack: contextlib.ExitStack | None = None

    def install(self) -> None:
        """安装 stderr 重定向。

        流程：
        1. os.dup(2) 备份原始 stderr fd
        2. 重定向 root logger 的所有 StreamHandler 到原始 fd（避免写管道死锁）
        3. os.pipe() 创建管道，os.dup2(write_fd, 2) 重定向 fd 2
        4. 启动 daemon 线程逐行读取管道，直接 os.write 到原始 fd

        幂等可重复调用。
        """
        with self._lock:
            if self._installed:
                return
            with contextlib.suppress(Exception):
                sys.stderr.flush()
            if self._original_fd is None:
                with contextlib.suppress(OSError):
                    self._original_fd = os.dup(2)
            if self._encoding is None:
                self._encoding = (
                    sys.stderr.encoding or locale.getpreferredencoding(False) or "utf-8"
                )

            # 重定向 root logger 的 StreamHandler：把 stream 替换为原始 fd 的副本
            # 避免主线程通过 root 写 fd 2（管道）→ 管道满时 emit 阻塞 → 死锁
            root_logger = logging.getLogger()
            self._saved_root_handlers = list(root_logger.handlers)
            self._saved_root_level = root_logger.level
            if self._original_fd is not None:
                # 创建写原始 fd 的 text stream（logging 期望 text mode）
                # encoding 用 sys.stderr 的 encoding 保持兼容
                # 使用 ExitStack 管理生命周期：install 时打开，uninstall 时关闭
                self._stream_stack = contextlib.ExitStack()
                orig_stream = self._stream_stack.enter_context(
                    _open_fd_stream(self._original_fd, self._encoding or "utf-8")
                )
                # 替换 root 现有 StreamHandler 的 stream，或新建一个
                replaced = False
                for h in list(root_logger.handlers):
                    if isinstance(h, logging.StreamHandler) and not isinstance(
                        h, logging.FileHandler
                    ):
                        # 保存原始 stream 以在 uninstall 时恢复（兼容 pytest logging plugin）
                        if id(h) not in self._saved_streams:
                            self._saved_streams[id(h)] = h.stream
                        # 替换 stream 为原始 fd（保留原 formatter/level）
                        h.stream = orig_stream
                        replaced = True
                if not replaced and not root_logger.handlers:
                    # root 无 handler，会用 lastResort（写 fd 2）。
                    # 添加一个写原始 fd 的 handler，并禁用 lastResort
                    new_handler = logging.StreamHandler(orig_stream)
                    new_handler.setFormatter(
                        logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
                    )
                    root_logger.addHandler(new_handler)
                    root_logger.setLevel(logging.INFO)
                # 禁用 lastResort，避免它写 fd 2（管道）
                logging.lastResort = None

            read_fd, write_fd = os.pipe()
            os.dup2(write_fd, 2)
            os.close(write_fd)
            self._read_fd = read_fd

            self._thread = threading.Thread(
                target=self._drain, name="illusion-stderr-redirect", daemon=True
            )
            self._thread.start()
            self._installed = True

    def uninstall(self) -> None:
        """卸载 stderr 重定向，恢复原始 fd 2。

        流程：os.dup2(original_fd, 2) 恢复 → join(timeout=2.0) 等 drain
        线程排空残留数据 → 恢复 root logger 配置。幂等可重复调用。
        """
        with self._lock:
            if not self._installed:
                return
            if self._original_fd is not None:
                os.dup2(self._original_fd, 2)
            self._installed = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        # 恢复 root logger 的原始 handler 配置
        root_logger = logging.getLogger()
        if self._saved_root_handlers is not None:
            # 恢复每个 handler 的原始 stream（兼容 pytest logging plugin）
            for h in self._saved_root_handlers:
                saved_stream = self._saved_streams.get(id(h))
                if saved_stream is not None and isinstance(h, logging.StreamHandler):
                    try:
                        h.stream = saved_stream
                    except (AttributeError, TypeError) as exc:
                        self._logger.debug("恢复 handler stream 失败: %s", exc)
            self._saved_streams.clear()
            # 关闭我们替换 stream 的 handler（释放原始 fd 副本）
            for h in list(root_logger.handlers):
                if h not in self._saved_root_handlers:
                    root_logger.removeHandler(h)
                    with contextlib.suppress(Exception):
                        h.close()
            # 恢复原始 handler
            root_logger.handlers = list(self._saved_root_handlers)
            self._saved_root_handlers = None
        if self._saved_root_level is not None:
            root_logger.setLevel(self._saved_root_level)
            self._saved_root_level = None
        # 恢复 lastResort 默认值
        from logging import _StderrHandler  # type: ignore
        logging.lastResort = _StderrHandler(logging.WARNING)
        # 关闭 install 中打开的原始 fd 副本 stream
        if self._stream_stack is not None:
            self._stream_stack.close()
            self._stream_stack = None

    def _drain(self) -> None:
        """daemon 线程主循环：逐行读取管道并直接 os.write 到原始 fd。

        不使用 logging 模块，避免 handler lock / handleError 死锁。
        """
        buffer = ""
        read_fd = self._read_fd
        if read_fd is None:
            return
        encoding = self._encoding or "utf-8"
        decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
        try:
            while True:
                chunk = os.read(read_fd, 4096)
                if not chunk:
                    break
                buffer += decoder.decode(chunk)
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    self._log_line(line)
        except OSError:
            # 读管道失败时静默退出，避免 daemon 线程崩溃
            pass
        finally:
            buffer += decoder.decode(b"", final=True)
            if buffer:
                self._log_line(buffer)
            with contextlib.suppress(OSError):
                os.close(read_fd)

    def _log_line(self, line: str) -> None:
        """将一行 stderr 输出直接 os.write 到原始 stderr fd。

        必须直接用 os.write，绕过 logging 模块。
        若用 logger.log() → handler emit 失败 → handleError 写 sys.stderr
        （fd 2 管道）→ 管道写阻塞 → 死锁。
        """
        text = line.rstrip("\r")
        if not text:
            return
        if self._original_fd is None:
            return
        try:
            data = f"[stderr] {text}\n".encode(self._encoding or "utf-8", errors="replace")
            os.write(self._original_fd, data)
        except OSError:
            # 原始 fd 不可写时静默丢弃，避免 daemon 线程崩溃
            pass

    def open_original_stderr_handle(self) -> IO[bytes] | None:
        """打开原始 stderr 的副本句柄，用于需要写真实 stderr 的场景。"""
        if self._original_fd is None:
            return None
        dup_fd = os.dup(self._original_fd)
        os.set_inheritable(dup_fd, True)
        return os.fdopen(dup_fd, "wb", closefd=True)
