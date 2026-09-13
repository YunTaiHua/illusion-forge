"""
Shell 和子进程辅助函数模块
=====================

本模块提供 shell 命令执行和子进程创建的跨平台支持功能。

主要功能：
    - 解析适合当前平台的最佳 shell 命令
    - 创建带有沙箱支持的异步子进程
    - 在 Windows 上智能查找可用的 bash 可执行文件

函数说明：
    - resolve_shell_command: 返回当前平台的最佳 shell 命令 argv
    - create_shell_subprocess: 创建带有沙箱支持的 shell 子进程
    - terminate_process_tree: 递归终止子进程及其整个进程树
    - _resolve_windows_bash: 解析 Windows 上可用的 bash 可执行文件

使用示例：
    >>> from illusion_forge.utils import resolve_shell_command
    
    >>> # 获取当前平台的 shell 命令
    >>> argv = resolve_shell_command("echo hello")
    >>> print(argv)  # ['bash', '-lc', 'echo hello']
    
    >>> # 创建子进程
    >>> process = await create_shell_subprocess("ls", cwd="/tmp")
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Coroutine, Mapping
from pathlib import Path
from typing import Any

from illusion_forge.config import Settings, load_settings
from illusion_forge.platforms import PlatformName, get_platform

# 模块级强引用集合，防止 fire-and-forget task 被 GC 抢收
_module_tasks: set[asyncio.Task[None]] = set()


def _create_module_task(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    """创建模块级 fire-and-forget task 并保留强引用。

    Args:
        coro: 要执行的协程

    Returns:
        创建的 task
    """
    task = asyncio.create_task(coro)
    _module_tasks.add(task)
    task.add_done_callback(_module_tasks.discard)
    return task


def resolve_shell_command(
    command: str,
    *,
    platform_name: PlatformName | None = None,
) -> list[str]:
    """
    解析适合当前平台的最佳 shell 命令
    
    根据平台类型自动选择最优的 shell 解释器：
    - Windows: 优先 WSL bash，其次 PowerShell，最后 cmd.exe
    - Unix/Linux/macOS: 优先 bash，其次 sh
    
    Args:
        command: 要执行的 shell 命令字符串
        platform_name: 指定平台名称，默认自动检测
    
    Returns:
        list[str]: shell 命令的 argv 列表，第一个元素为可执行文件路径
    
    使用示例：
        >>> argv = resolve_shell_command("ls -la")
        >>> argv  # ['bash', '-lc', 'ls -la']
    """
    resolved_platform = platform_name or get_platform()
    # Windows 平台优先尝试 WSL bash
    if resolved_platform == "windows":
        bash = _resolve_windows_bash()
        if bash:
            return [bash, "-lc", command]
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell:
            return [powershell, "-NoLogo", "-NoProfile", "-Command", command]
        return [shutil.which("cmd.exe") or "cmd.exe", "/d", "/s", "/c", command]

    # Unix 系统优先使用 bash
    bash = shutil.which("bash")
    if bash:
        return [bash, "-lc", command]
    shell = shutil.which("sh") or os.environ.get("SHELL") or "/bin/sh"
    return [shell, "-lc", command]


# 子进程中需要剥离的变量（认证/配置类，统一通过 settings.json 管理）
# 精确匹配：仅剥离这些确切名称的变量
_ENV_STRIP_EXACT: frozenset[str] = frozenset({
    "ILLUSION_MODEL",
    "ILLUSION_EFFORT",
})
# 前缀匹配：剥离以这些前缀开头的所有变量
_ENV_STRIP_PREFIXES: tuple[str, ...] = (
    "ANTHROPIC_",
    "OPENAI_",
    "CLAUDE_",
    "ILLUSION_API_",
    "ILLUSION_BASE_",
    "ILLUSION_MAX_",
    "ILLUSION_SANDBOX_",
)


def _build_filtered_env() -> dict[str, str]:
    """构建过滤后的子进程环境变量。

    剥离认证/配置类变量（ANTHROPIC_*、OPENAI_*、CLAUDE_*、ILLUSION_* 等），
    保留代理、证书、系统变量（HTTP_PROXY、SSL_CERT_FILE、PATH、HOME 等）。
    """
    result: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if upper in _ENV_STRIP_EXACT:
            continue
        if any(upper.startswith(prefix) for prefix in _ENV_STRIP_PREFIXES):
            continue
        result[key] = value
    return result


async def create_shell_subprocess(
    command: str,
    *,
    cwd: str | Path,
    settings: Settings | None = None,
    disable_sandbox: bool = False,
    stdin: int | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    env: Mapping[str, str] | None = None,
    new_process_group: bool = False,
) -> asyncio.subprocess.Process:
    """
    创建带有平台感知和沙箱支持的 shell 子进程
    
    自动解析适合平台的 shell 命令，并应用沙箱包装（如果启用）。
    
    Args:
        command: 要执行的 shell 命令
        cwd: 工作目录
        settings: 配置对象，默认自动加载
        disable_sandbox: 是否绕过沙箱包装
        stdin: 标准输入文件描述符
        stdout: 标准输出文件描述符
        stderr: 标准错误文件描述符
        environment: 环境变量映射
    
    Returns:
        asyncio.subprocess.Process: 异步子进程对象
    
    使用示例：
        >>> process = await create_shell_subprocess("ls", cwd="/tmp")
        >>> await process.wait()
    """
    resolved_settings = settings or load_settings()
    argv = resolve_shell_command(command)

    return await create_argv_subprocess(
        argv,
        cwd=cwd,
        settings=resolved_settings,
        command=command,
        disable_sandbox=disable_sandbox,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        env=env,
        new_process_group=new_process_group,
    )


async def create_argv_subprocess(
    argv: list[str],
    *,
    cwd: str | Path,
    settings: Settings | None = None,
    command: str | None = None,
    disable_sandbox: bool = False,
    stdin: int | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    env: Mapping[str, str] | None = None,
    new_process_group: bool = False,
) -> asyncio.subprocess.Process:
    """
    基于显式 argv 创建带沙箱支持的子进程

    与 create_shell_subprocess 的区别：接收已解析的 argv（首元素为可执行文件
    路径），而非原始命令字符串。供 PowerShell 等需显式指定解释器参数的工具使用，
    保证与 bash 一致的沙箱覆盖与 YOLO 模式行为。

    Args:
        argv: 已解析的可执行文件 argv（首元素为可执行文件路径）
        cwd: 工作目录
        settings: 配置对象，默认自动加载
        command: 原始命令字符串（用于沙箱排除命令匹配；缺省时回退到 argv[0]）
        disable_sandbox: 是否绕过沙箱包装
        stdin: 标准输入文件描述符
        stdout: 标准输出文件描述符
        stderr: 标准错误文件描述符
        env: 环境变量映射
        new_process_group: 是否创建独立进程组

    Returns:
        asyncio.subprocess.Process: 异步子进程对象
    """
    resolved_settings = settings or load_settings()
    # 沙箱排除命令匹配应基于原始命令字符串（如 PowerShell 的 -Command 参数），
    # 而非可执行文件路径；缺省时回退到 argv[0]。
    exclusion_command = command or argv[0]

    # 使用沙箱包装命令（如果配置启用且未显式禁用）
    sandbox_manager = None
    if not disable_sandbox:
        from illusion_forge.sandbox import SandboxManager

        sandbox_manager = SandboxManager()
        if sandbox_manager.should_use_sandbox(exclusion_command, settings=resolved_settings):
            argv = sandbox_manager.wrap_command(argv, shell=argv[0])

    try:
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            if new_process_group:
                kwargs["creationflags"] |= subprocess.CREATE_NEW_PROCESS_GROUP
        elif new_process_group:
            # POSIX：独立会话，使整个命令树处于独立进程组，便于 killpg 终止
            kwargs["start_new_session"] = True
        # 显式过滤子进程环境：剥离认证/配置类变量，保留代理/证书/系统变量
        child_env = env if env is not None else _build_filtered_env()
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(Path(cwd).resolve()),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=child_env,
            **kwargs,
        )
    except Exception:
        # 发生异常时清理沙箱
        if sandbox_manager:
            sandbox_manager.cleanup_after_command()
        raise

    # 进程结束后异步清理沙箱
    if sandbox_manager:
        _create_module_task(_cleanup_sandbox_after_exit(process, sandbox_manager))
    return process


async def terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    """终止子进程及其整个进程树。

    子进程以独立进程组启动（create_shell_subprocess new_process_group=True），
    按平台杀进程树：

    - Windows: taskkill /PID <pid> /T /F（/T 递归终止所有子进程）
    - POSIX: killpg 先 SIGTERM，3s 未退出再 SIGKILL

    Args:
        process: 要终止的子进程
    """
    if sys.platform == "win32":
        try:
            # CREATE_NO_WINDOW：taskkill 自身是控制台程序，不隐藏会弹出终端黑框
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(killer.wait(), timeout=5)
        except (OSError, subprocess.SubprocessError):
            # taskkill 不可用时回退到直接 terminate
            with contextlib.suppress(ProcessLookupError, OSError):
                process.terminate()
        # taskkill /F 已强杀进程，wait 仅回收句柄；Windows 上偶发长时间不
        # signaled，缩短超时避免 stop 延迟
        with contextlib.suppress(TimeoutError, ProcessLookupError, OSError):
            await asyncio.wait_for(process.wait(), timeout=0.5)
        return

    # POSIX：kill 进程组
    try:
        child_pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        return  # 进程已退出
    # 仅当子进程处于独立进程组时才能 killpg：若与当前进程同组
    # （如测试/未设置 new_process_group 的调用方直接用 create_subprocess_exec），
    # killpg 会把信号发给包含自己的进程组（CI runner 曾因此被 SIGTERM 击杀挂死），
    # 此时退化为只终止进程本身。
    if child_pgid == os.getpgid(os.getpid()):
        with contextlib.suppress(ProcessLookupError, OSError):
            process.kill()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=2)
        return
    with contextlib.suppress(ProcessLookupError, OSError):
        os.killpg(child_pgid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=3)
        return
    except TimeoutError:
        pass
    with contextlib.suppress(ProcessLookupError, OSError):
        os.killpg(child_pgid, signal.SIGKILL)
    # 关闭管道强制 EOF，避免 wait() 因管道被孙子进程继承持有而永久挂住
    for pipe in (process.stdin, process.stdout, process.stderr):
        if pipe is not None:
            with contextlib.suppress(Exception):
                pipe.close()
    with contextlib.suppress(TimeoutError, Exception):
        await asyncio.wait_for(process.wait(), timeout=2)


async def _cleanup_after_exit(process: asyncio.subprocess.Process, cleanup_path: Path) -> None:
    """进程退出后清理沙箱临时文件（向后兼容）"""
    try:
        await process.wait()
    finally:
        cleanup_path.unlink(missing_ok=True)


async def _cleanup_sandbox_after_exit(
    process: asyncio.subprocess.Process,
    manager: Any,
) -> None:
    """进程退出后清理沙箱资源"""
    try:
        await process.wait()
    finally:
        manager.cleanup_after_command()


def _resolve_windows_bash() -> str | None:
    """
    解析 Windows 上可用的 bash 可执行文件
    
    忽略传统的 Windows 系统 shim（C:\\Windows\\System32\\bash.exe），
    该位置可能在未配置 WSL 的机器上失败或输出无法读取的内容。
    
    解析优先级：
        1. ILLUSION_AGENT_GIT_BASH_PATH 环境变量覆盖
        2. 通过 PATH 找到的 bash（排除 system32 shim）
        3. 从 git 可执行文件位置解析 bash
        4. 在已知的 Git for Windows 安装路径中查找
    
    Returns:
        str | None: bash 可执行文件路径，未找到则返回 None
    """
    # 1. 通过环境变量显式指定
    env_bash = os.environ.get("ILLUSION_AGENT_GIT_BASH_PATH")
    if env_bash and Path(env_bash).exists():
        return env_bash

    # 2. PATH 上的 bash（跳过传统的 system32 shim）
    bash = shutil.which("bash")
    if bash and not _is_windows_bash_shim(bash):
        return bash

    # 3. 从 git 可执行文件位置解析 bash
    git_path = shutil.which("git")
    if git_path:
        # git.exe 通常位于 <Git-Root>\cmd\git.exe 或 <Git-Root>\bin\git.exe
        # bash.exe 位于 <Git-Root>\bin\bash.exe
        git_root = Path(git_path).resolve().parent.parent
        bash_via_git = git_root / "bin" / "bash.exe"
        if bash_via_git.exists():
            return str(bash_via_git)

    # 4. 在已知的 Git for Windows 安装路径中搜索
    for candidate in _windows_git_bash_candidates():
        if candidate.exists():
            return str(candidate)

    return None


def _windows_git_bash_candidates() -> list[Path]:
    """
    生成已知的 Git for Windows 安装路径候选列表
    
    在常见的 Program Files 目录中查找 Git 安装路径。
    
    Returns:
        list[Path]: 可能的 bash.exe 路径列表
    """
    roots: list[str] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        value = os.environ.get(key)
        if value:
            roots.append(value)

    candidates: list[Path] = []
    for root in roots:
        base = Path(root)
        candidates.append(base / "Git" / "bin" / "bash.exe")
        candidates.append(base / "Git" / "usr" / "bin" / "bash.exe")
        candidates.append(base / "Programs" / "Git" / "bin" / "bash.exe")
        candidates.append(base / "Programs" / "Git" / "usr" / "bin" / "bash.exe")
    return candidates


def _is_windows_bash_shim(path: str) -> bool:
    """
    检查路径是否为 Windows system32 bash shim
    
    判断给定路径是否为传统的 Windows system32 bash 替身（shim），
    这是一个空壳程序，不提供真正的 bash 功能。
    
    Args:
        path: 要检查的可执行文件路径
    
    Returns:
        bool: 是否为 system32 shim
    """
    normalized = path.replace("/", "\\").lower()
    return normalized.endswith("\\windows\\system32\\bash.exe")