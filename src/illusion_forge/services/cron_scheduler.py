"""
Cron 调度器模块
===============

非阻塞、独立会话执行的定时任务调度器。

核心设计：
    - 调度器作为后台 asyncio 任务运行，不阻塞当前会话
    - 每个到期任务在独立子进程中执行（通过 illusion-forge -p 启动）
    - 使用本地时间进行调度判断
    - 支持错误退避和连续错误跟踪
    - 跨平台兼容（Windows / Linux / macOS）

主要组件：
    - CronScheduler: 调度器类，管理后台调度循环
    - append_history / load_history: 执行历史记录
    - scheduler_status: 调度器状态查询
    - ensure_started: 确保调度器正在运行（创建任务时自动调用）

使用示例：
    >>> from illusion_forge.services.cron_scheduler import get_scheduler, ensure_started
    >>> await ensure_started()      # 确保调度器运行
    >>> scheduler = get_scheduler()
    >>> scheduler.is_running        # 检查状态
    >>> await scheduler.stop()      # 停止调度
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from illusion_forge.config.paths import get_cron_dir, get_logs_dir
from illusion_forge.services.cron import (
    load_cron_jobs,
    mark_job_run,
    remove_expired_jobs,
    validate_cron_expression,
)

# 模块级日志记录器
logger = logging.getLogger(__name__)

# 调度周期间隔（秒）- 每 30 秒检查一次到期任务
TICK_INTERVAL_SECONDS = 30
"""调度器检查到期任务的频率（秒）。"""

# 错误退避策略（秒）：连续错误后逐渐增加等待时间

_ERROR_BACKOFF_SECONDS = [30, 60, 300, 900, 3600]
"""错误退避时间序列（秒），按连续错误次数索引。"""

# 任务执行超时（秒）
_JOB_TIMEOUT_SECONDS = 300
"""单个任务的执行超时时间（秒），默认 5 分钟。"""

# 最大并发任务数
_MAX_CONCURRENT_JOBS = 1
"""同时执行的最大任务数。"""


# ---------------------------------------------------------------------------
# 历史记录
# ---------------------------------------------------------------------------

def get_history_path() -> Path:
    """返回 Cron 执行历史记录文件路径。"""
    return get_cron_dir() / "history.jsonl"


def append_history(entry: dict[str, Any]) -> None:
    """向历史日志追加一条执行记录。

    每条记录包含：name, prompt, started_at, ended_at, returncode, status, stdout, stderr。
    """
    path = get_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_history(
    *,
    limit: int = 50,
    job_name: str | None = None,
    job_id: str | None = None,
) -> list[dict[str, Any]]:
    """加载最近的执行历史记录。

    Args:
        limit: 最大返回条数
        job_name: 按任务名称过滤
        job_id: 按任务 ID 过滤

    Returns:
        历史记录列表，按时间正序排列
    """
    path = get_history_path()
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if job_name and entry.get("name") != job_name:
            continue
        if job_id and entry.get("id") != job_id:
            continue
        entries.append(entry)
    return entries[-limit:]


# ---------------------------------------------------------------------------
# PID 文件管理
# ---------------------------------------------------------------------------

def get_pid_path() -> Path:
    """返回调度器 PID 文件路径。"""
    return get_cron_dir() / "scheduler.pid"


def _is_process_alive(pid: int) -> bool:
    """检查给定 PID 的进程是否存活（跨平台安全）。

    注意：Windows 上 os.kill(pid, 0) 会发送 CTRL_C_EVENT（signal 0 == CTRL_C_EVENT），
    而非 POSIX 上的无操作检测，因此必须使用 OpenProcess 替代。
    """
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000 (Vista+)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def read_pid() -> int | None:
    """读取运行中的调度器 PID，如果不存在或进程已退出则返回 None。"""
    path = get_pid_path()
    if not path.exists():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None
    if not _is_process_alive(pid):
        logger.debug("Removed stale scheduler PID file (pid=%d)", pid)
        path.unlink(missing_ok=True)
        return None
    return pid


def write_pid(pid: int) -> None:
    """写入指定的进程 PID。"""
    path = get_pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid) + "\n", encoding="utf-8")


def remove_pid() -> None:
    """删除 PID 文件。"""
    get_pid_path().unlink(missing_ok=True)


def is_scheduler_running() -> bool:
    """返回是否存在运行的调度器进程。"""
    return read_pid() is not None


# ---------------------------------------------------------------------------
# 错误退避计算
# ---------------------------------------------------------------------------

def _get_backoff_seconds(consecutive_errors: int) -> int:
    """根据连续错误次数返回退避等待时间（秒）。

    使用预定义的退避序列，超出序列范围则使用最大值。
    """
    if consecutive_errors <= 0:
        return 0
    index = min(consecutive_errors - 1, len(_ERROR_BACKOFF_SECONDS) - 1)
    return _ERROR_BACKOFF_SECONDS[index]


# ---------------------------------------------------------------------------
# 可执行文件查找
# ---------------------------------------------------------------------------

def _find_illusion_command() -> list[str]:
    """查找 illusion-forge 命令，返回可作为 subprocess 参数的命令列表。

    优先级：
    1. PATH 中的 illusion-forge 可执行文件（pip install 后可用）
    2. python -m illusion_forge（开发模式 / 模块运行）
    """
    # 方式 1：查找 PATH 中的 illusion-forge 命令
    which = shutil.which("illusion-forge")
    if which:
        return [which]

    # 方式 2：使用当前 Python 解释器运行模块
    return [sys.executable, "-m", "illusion_forge"]


# ---------------------------------------------------------------------------
# 任务执行
# ---------------------------------------------------------------------------


def _filter_mcp_log_noise(stderr_text: str) -> str:
    """过滤 stderr 中 MCP 日志文件相关的噪声行。

    MCP 服务器的 stderr 输出（如 log_file 路径引用）不应出现在 cron 历史中。

    Args:
        stderr_text: 原始 stderr 文本

    Returns:
        过滤后的 stderr 文本
    """
    import re
    lines = stderr_text.splitlines(keepends=True)
    filtered = []
    for line in lines:
        # 跳过包含 mcp.log 或 .mcp. 日志文件路径的行
        if re.search(r'[\w/\\.-]*mcp[\w/\\-]*\.log', line, re.IGNORECASE):
            continue
        filtered.append(line)
    return "".join(filtered)


async def _execute_prompt_in_subprocess(
    prompt: str,
    cwd: Path,
    timeout: int = _JOB_TIMEOUT_SECONDS,
    extra_env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """在独立子进程中执行提示词。

    通过 `illusion-forge -p "<prompt>"` 启动独立会话，
    确保不阻塞当前会话，且任务在隔离环境中运行。

    Args:
        prompt: 要执行的提示词
        cwd: 工作目录
        timeout: 超时秒数
        extra_env: 额外环境变量（如 ILLUSION_CRON_TASK=1，用于子进程识别 cron 上下文）
        extra_args: 额外命令行参数（如指定会话执行时追加 -r <session_id> --cwd）

    Returns:
        包含 returncode, stdout, stderr, status 的结果字典
    """
    cmd = _find_illusion_command() + ["-p", prompt]
    if extra_args:
        cmd.extend(extra_args)

    # 合并环境变量：继承父进程 + 额外变量
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)

    logger.info("Executing cron subprocess: %s", " ".join(cmd[:3]) + " -p <prompt>")
    logger.debug("Full command: %s, cwd: %s", cmd, cwd)

    try:
        # Windows: 使用 CREATE_NO_WINDOW 防止弹出黑色控制台窗口
        # 非 Windows 平台该标志不存在，设为 0 不影响行为
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        process: asyncio.subprocess.Process | None = None
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Windows: 防止句柄继承死锁
            stdin=asyncio.subprocess.DEVNULL,
            # Windows: 不弹出控制台窗口
            creationflags=creationflags,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
    except TimeoutError:
        # 超时处理：终止子进程
        if process is not None:  # pyright: ignore[reportPossiblyUnboundVariable]
            try:
                process.kill()  # pyright: ignore[reportPossiblyUnboundVariable]
                await process.wait()  # pyright: ignore[reportPossiblyUnboundVariable]
            except (ProcessLookupError, OSError) as kill_exc:
                # 进程已退出或无法终止 — 超时清理是尽力而为
                logger.debug("Failed to kill timed-out cron subprocess: %s", kill_exc)
        logger.warning("Cron subprocess timed out after %ds", timeout)
        return {
            "returncode": -1,
            "status": "timeout",
            "stdout": "",
            "stderr": f"Job timed out after {timeout}s",
        }
    except asyncio.CancelledError:
        if process is not None:  # pyright: ignore[reportPossiblyUnboundVariable]
            try:
                process.kill()  # pyright: ignore[reportPossiblyUnboundVariable]
            except (ProcessLookupError, OSError):
                pass
            with contextlib.suppress(Exception):
                await process.wait()  # pyright: ignore[reportPossiblyUnboundVariable]
        raise
    except FileNotFoundError as exc:
        # illusion-forge 命令未找到
        logger.error("Failed to start cron subprocess: %s", exc)
        return {
            "returncode": -1,
            "status": "error",
            "stdout": "",
            "stderr": f"illusion-forge command not found: {exc}",
        }
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        logger.error("Failed to start cron subprocess: %s", exc)
        return {
            "returncode": -1,
            "status": "error",
            "stdout": "",
            "stderr": str(exc),
        }

    success = process.returncode == 0
    stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

    # 过滤 MCP 日志文件相关的输出（如 mcp.log 文件路径引用）
    if stderr_text:
        stderr_text = _filter_mcp_log_noise(stderr_text)

    # 记录子进程 stderr 到日志（便于调试）
    if stderr_text.strip():
        logger.debug("Cron subprocess stderr: %s", stderr_text[:500])

    if not success:
        logger.warning(
            "Cron subprocess exited with rc=%d, stderr: %s",
            process.returncode,
            stderr_text[:200],
        )

    return {
        "returncode": process.returncode,
        "status": "success" if success else "failed",
        "stdout": (stdout.decode("utf-8", errors="replace")[-2000:] if stdout else ""),
        "stderr": stderr_text[-2000:] if stderr_text else "",
    }


def _build_cron_context_prefix(
    deliver_to_list: list[str],
    chat_id: str,
) -> str | None:
    """构建 cron 任务上下文前缀（渠道身份提示）。

    不告知 LLM「输出会被投递到某渠道」——那样 LLM 会在回复末尾画蛇添足地
    声明「发送完成/已发送到 XX 频道」。改为直接告知当前所在渠道，让 LLM
    以该渠道身份说话；投递由系统自动完成，无需 LLM 提及。

    Args:
        deliver_to_list: 投递目标列表（channel:chat_id 或 channel-only）
        chat_id: 来源会话 ID（渠道-only 目标解析用）

    Returns:
        str | None: 前缀文本；无有效投递目标时返回 None
    """
    if not deliver_to_list:
        return None
    from illusion_forge.channels.delivery import parse_deliver_targets

    targets = parse_deliver_targets(deliver_to_list, chat_id)
    if not targets:
        return None
    channel_names = sorted({t[0] for t in targets})
    channel_labels = {"feishu": "Feishu", "weixin": "WeChat", "qq": "QQ"}
    display = ", ".join(channel_labels.get(c, c) for c in channel_names)
    return (
        "[CRON TASK CONTEXT]\n"
        "You are running as an automated cron task.\n"
        f"You are currently in the {display} channel(s) — speak directly as yourself there.\n"
        "Just output the message content; the system delivers it to the channel automatically.\n"
        "Do NOT mention delivery in your reply (never say things like 'sent to ...' / '已发送').\n"
        "Do NOT call send_to_channel / send_media / list_channel_sessions tools.\n\n"
    )


def _resolve_cron_permission_mode(job: dict[str, Any]) -> str:
    """解析 cron 任务执行时的权限模式。

    依据投递目标与指定会话决定子进程的 `--permission-mode`：
    - 无投递目标且无指定会话 → yolo（无人值守独立任务，绕过权限与沙箱）
    - 有投递目标（无指定会话）→ 渠道端语义：权限自动批准由环境变量
      ILLUSION_CRON_AUTO_APPROVE 触发，权限模式沿用 settings.permission.mode
      （保留沙箱限制，与渠道 bot 一致）
    - 有指定会话 → 继承当前 settings.permission.mode

    Args:
        job: cron 任务字典（含 deliver_to / session_id 字段）

    Returns:
        str: 权限模式字符串（default/plan/full_auto/yolo）
    """
    from illusion_forge.config.settings import load_settings
    from illusion_forge.permissions.modes import PermissionMode

    session_id = str(job.get("session_id") or "").strip()
    deliver_to_list = job.get("deliver_to", []) or []
    if not session_id and not deliver_to_list:
        # 无投递无会话：独立无人值守任务，绕过权限与沙箱保证跑通
        return PermissionMode.YOLO.value
    # 有指定会话或有投递目标：沿用当前 settings 权限模式（继承当前配置）
    return load_settings().permission.mode.value or PermissionMode.DEFAULT.value


def validate_job_targets(job: dict[str, Any]) -> list[str]:
    """校验任务引用的会话目标是否存在（session_id / deliver_to）。

    任务到期执行前调用：若指定的项目会话或渠道会话已被删除（找不到对应
    ID），返回错误列表，调用方据此拒绝执行（避免投递/执行到无效目标）。

    Args:
        job: 任务字典（含 cwd / session_id / deliver_to 字段）

    Returns:
        list[str]: 错误消息列表（空列表 = 校验通过）
    """
    errors: list[str] = []
    cwd = Path(job.get("cwd") or ".").expanduser()

    # 1. 指定项目会话存在性
    session_id = str(job.get("session_id") or "").strip()
    if session_id:
        from illusion_forge.services.session_storage import read_meta

        meta = read_meta(cwd, session_id)
        if not meta:
            errors.append(f"Session not found: {session_id}")

    # 2. 渠道投递目标存在性（channel:chat_id 格式，逐个解析校验）
    deliver_to_list = job.get("deliver_to", []) or []
    if isinstance(deliver_to_list, str):
        # 兼容旧格式/错误数据：字符串视为单目标列表
        deliver_to_list = [deliver_to_list]
    if deliver_to_list:
        from illusion_forge.channels.delivery import parse_deliver_targets

        # 传来源会话 chat_id：兼容渠道-only 格式（如 ["weixin"]，由创建时的
        # chat_id 解析出完整目标），与 execute_job 实际投递逻辑保持一致
        targets = parse_deliver_targets(
            deliver_to_list,
            chat_id=str(job.get("chat_id") or ""),
        )
        if not targets:
            errors.append("deliver_to has no valid targets")
        else:
            from illusion_forge.channels.config import load_channels_config
            from illusion_forge.prompts.channel_hints import list_active_sessions

            cfg = load_channels_config()
            for channel_name, chat_id, _chat_type in targets:
                channel_cfg = getattr(cfg, channel_name, None)
                if channel_cfg is None or not getattr(channel_cfg, "enabled", False):
                    errors.append(f"Channel not enabled: {channel_name}")
                    continue
                # 渠道会话存在性：活跃会话列表匹配（会话文件被删除后不再出现）
                sessions = list_active_sessions(channel_name, cfg, limit=1000)
                if chat_id not in {s.chat_id for s in sessions}:
                    errors.append(f"Channel session not found: {channel_name}:{chat_id}")

    return errors


async def execute_job(
    job: dict[str, Any],
    timeout: int = _JOB_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """执行单个 Cron 任务并返回历史记录条目。

    任务通过 `illusion-forge -p` 在独立子进程中执行，不阻塞当前会话。

    Args:
        job: 任务字典，包含 name, prompt, cwd 等字段
        timeout: 子进程执行超时秒数，默认 300

    Returns:
        历史记录条目字典
    """
    name = job.get("name", job.get("id", "unknown"))
    prompt = job.get("prompt", "")
    cwd = Path(job.get("cwd") or ".").expanduser()
    started_at = _now_local()

    if not prompt:
        entry = {
            "id": job.get("id", ""),
            "name": name,
            "prompt": prompt,
            "started_at": started_at.isoformat(),
            "ended_at": _now_local().isoformat(),
            "returncode": -1,
            "status": "error",
            "stdout": "",
            "stderr": "Job has no prompt field",
        }
        logger.error("Cron job %r has no prompt, skipping", name)
        mark_job_run(job.get("id", name), success=False, status="error")
        append_history(entry)
        return entry

    # 目标会话校验：session_id / deliver_to 引用的会话已被删除时拒绝执行
    errors = validate_job_targets(job)
    if errors:
        detail = "\n".join(errors)
        entry = {
            "id": job.get("id", ""),
            "name": name,
            "prompt": prompt,
            "started_at": started_at.isoformat(),
            "ended_at": _now_local().isoformat(),
            "returncode": -1,
            "status": "error",
            "stdout": "",
            "stderr": f"Job targets invalid, execution rejected:\n{detail}",
        }
        logger.warning("Cron job %r targets invalid, rejected: %s", name, detail)
        mark_job_run(job.get("id", name), success=False, status="error")
        append_history(entry)
        return entry

    logger.info("Executing cron job %r: %.80s", name, prompt)

    # 拼接 cron 上下文前缀：以渠道身份提示告知 LLM 当前所在渠道
    # （避免 LLM 在回复末尾声明"已发送到 XX 频道"），并阻止其调用投递工具
    deliver_to_list = job.get("deliver_to", []) or []
    if isinstance(deliver_to_list, str):
        # 兼容旧格式/错误数据：字符串视为单目标列表
        deliver_to_list = [deliver_to_list]
    cron_prefix = _build_cron_context_prefix(
        deliver_to_list, str(job.get("chat_id") or ""),
    )
    if cron_prefix:
        actual_prompt = cron_prefix + prompt
    else:
        actual_prompt = prompt

    # 指定会话执行（job.session_id 存在时）：优先委托给正在运行的 Web 主程序
    # 在内存会话中执行（busy 转化、web 列表刷新天然正确）；领取窗口内无人接管
    # 或总超时后回退为子进程 `illusion-forge -p <prompt> -r <session_id>` 恢复会话执行。
    session_id = str(job.get("session_id") or "").strip()
    delegated_entry = None
    if session_id:
        # 委托执行使用带前缀的提示词：主程序在目标会话中执行时同样需要
        # CRON 上下文提示（scheduler 负责投递），否则 LLM 可能自行调用
        # send_to_channel 造成双重投递。复制 job 避免污染调用方字典。
        delegated_entry = await _try_delegate_execution(
            {**job, "prompt": actual_prompt}, timeout,
        )

    # 解析 cron 执行权限模式（依据投递目标 / 指定会话）：
    #   - 无投递目标且无指定会话 → yolo（无人值守独立任务，绕过权限与沙箱）
    #   - 有投递目标 → 渠道端语义：权限自动批准（环境变量触发）+ 保留沙箱
    #   - 有指定会话 → 继承当前 settings.permission.mode
    # 权限模式通过环境变量 ILLUSION_PERMISSION_MODE 传递（临时、不持久化），
    # 而非 --permission-mode CLI 参数——后者会持久化到 settings.json，
    # 污染主会话的全局权限配置。
    permission_mode = _resolve_cron_permission_mode(job)

    # 设置环境变量标记 cron 任务上下文，子进程据此屏蔽 channel_hints 注入
    extra_env: dict[str, str] = {"ILLUSION_PERMISSION_MODE": permission_mode}
    if deliver_to_list:
        extra_env["ILLUSION_CRON_TASK"] = "1"
        # 有投递且未指定会话：对齐渠道端行为——print 模式权限回调自动批准所有
        # 工具权限（含高危），但保留沙箱限制（与渠道 bot 一致）
        if not session_id:
            extra_env["ILLUSION_CRON_AUTO_APPROVE"] = "1"

    # 在独立子进程中执行提示词（委托未接管时）
    if delegated_entry is None:
        if session_id:
            # 指定会话执行的回退路径：恢复指定会话（-r）后执行
            result = await _execute_prompt_in_subprocess(
                actual_prompt, cwd, timeout=timeout, extra_env=extra_env,
                extra_args=["-r", session_id, "--cwd", str(cwd)],
            )
        else:
            result = await _execute_prompt_in_subprocess(
                actual_prompt, cwd, timeout=timeout, extra_env=extra_env,
            )
        ended_at = _now_local()
        success = result["status"] == "success"
    else:
        result = delegated_entry
        ended_at = _now_local()
        success = result["status"] == "success"

    # 投递到渠道：仅在 deliver_to 非空且有输出（stdout 或 stderr）时触发
    # 失败不影响任务状态，仅记录日志
    chat_id = job.get("chat_id", "")
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")

    # 组装投递文本：成功时仅送 stdout；失败时附带 stderr 让用户可见错误
    if not success and stderr:
        output = f"{stdout}\n--- stderr ---\n{stderr}" if stdout else stderr
    else:
        output = stdout

    # 诊断日志：确认投递分支的判断条件
    logger.info(
        "Cron deliver check: job=%r deliver_to_list=%r chat_id=%r stdout_len=%d stderr_len=%d output_strip=%s",
        name, deliver_to_list, chat_id, len(stdout), len(stderr), bool(output.strip()),
    )

    if deliver_to_list and output and output.strip():
        try:
            from illusion_forge.channels.delivery import (
                deliver_to_channel,
                parse_deliver_targets,
            )

            targets = parse_deliver_targets(deliver_to_list, chat_id)
            logger.info(
                "Cron deliver parse: deliver_to_list=%r -> targets=%r",
                deliver_to_list, targets,
            )
            if targets:
                # 广播到所有目标：每个目标独立投递，单点失败不影响其他目标
                for channel_name, target_chat_id, target_chat_type in targets:
                    try:
                        deliver_ok = await deliver_to_channel(
                            channel_name, target_chat_id, output,
                            chat_type=target_chat_type,
                        )
                        logger.info(
                            "Cron deliver result: job=%r channel=%s chat_id=%s ok=%s output_len=%d",
                            name, channel_name, target_chat_id, deliver_ok, len(output),
                        )
                        if not deliver_ok:
                            logger.warning(
                                "Cron job %s 投递到 %s:%s 失败",
                                name, channel_name, target_chat_id,
                            )
                    except Exception as exc:
                        # 单目标异常不中断其他目标
                        logger.warning(
                            "Cron 投递到 %s:%s 异常: %s",
                            channel_name, target_chat_id, exc,
                            exc_info=True,
                        )
        except Exception as exc:
            logger.warning("Cron 投递整体异常: %s", exc, exc_info=True)

    entry = {
        "id": job.get("id", ""),
        "name": name,
        "prompt": prompt,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "returncode": result["returncode"],
        "status": result["status"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }

    # 更新任务执行状态
    mark_job_run(job.get("id", name), success=success, status=result["status"])

    # 记录历史
    append_history(entry)
    logger.info(
        "Cron job %r finished: status=%s rc=%s",
        name,
        result["status"],
        result["returncode"],
    )

    return entry


async def _try_delegate_execution(
    job: dict[str, Any],
    timeout: int = _JOB_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """尝试将指定会话任务委托给正在运行的 Web 主程序执行。

    流程：
    1. 登记待委托任务到 cron_delegation 队列
    2. 等待主程序领取并回报结果（总等待 = 领取窗口 + 执行超时）
    3. 主程序回报 not_supported（cwd/会话不匹配）时由 IPC 侧重新入队，
       本函数继续等待其他主程序领取
    4. 总超时后：任务仍在队列（无人领取）→ 回收并返回 None（回退子进程）；
       任务已被领取（在途执行）→ 返回超时 entry（与子进程超时行为一致，
       避免子进程与主程序双执行）

    Args:
        job: 任务字典（须包含 id 与 session_id）
        timeout: 委托执行超时秒数

    Returns:
        dict | None: 委托执行结果（与子进程结果同构）；需回退子进程时返回 None
    """
    from illusion_forge.services import cron_delegation

    # 非守护进程（Web 主程序、手动 run / web run 按钮）：本地注册的任务
    # 无人领取（claim 只发生在守护进程的 IPC handler），直接回退子进程，
    # 避免白等领取窗口 + 执行超时（330s）。
    if not cron_delegation.is_served():
        logger.debug("cron 委托队列未被本进程服务，跳过委托: id=%s", job.get("id", ""))
        return None

    job_id = str(job.get("id", ""))
    future = cron_delegation.register_pending_job(job)
    total_wait = cron_delegation.CLAIM_WINDOW_SECONDS + timeout
    try:
        result = await asyncio.wait_for(future, timeout=total_wait)
    except asyncio.TimeoutError:
        # 总超时：任务未被领取则回收并回退子进程；已被领取则视为执行超时
        if cron_delegation.cancel_pending(job_id):
            logger.info("cron 委托无人接管（%ds），回退子进程: id=%s", total_wait, job_id)
            return None
        logger.warning("cron 委托执行超时（%ds）: id=%s", total_wait, job_id)
        return {
            "returncode": -1,
            "status": "timeout",
            "stdout": "",
            "stderr": f"Delegated cron job timed out after {total_wait}s",
        }
    finally:
        # 未完成且仍在队列的 future 兜底清理（正常路径由 report/cancel/reap 处理）
        if not future.done():
            cron_delegation.cancel_pending(job_id)

    if result.get("status") == "unclaimed":
        # 领取窗口耗尽（无人领取），回退子进程
        logger.info("cron 委托领取窗口耗尽，回退子进程: id=%s", job_id)
        return None

    # 主程序回报的实际执行结果（success/failed/error 等）
    logger.info(
        "cron 委托执行完成: id=%s status=%s",
        job_id, result.get("status"),
    )
    return {
        "returncode": int(result.get("returncode", -1)),
        "status": str(result.get("status", "error")),
        "stdout": str(result.get("stdout", "")),
        "stderr": str(result.get("stderr", "")),
    }


def _now_local() -> datetime:
    """返回本地时间。"""
    # 通过 UTC → 本地时区 → 移除 tzinfo 的路径获取无时区的本地时间，
    # 避免 datetime.now() 不带 tz 参数（DTZ005）。
    return datetime.now(UTC).astimezone().replace(tzinfo=None, microsecond=0)


# ---------------------------------------------------------------------------
# 调度器核心类
# ---------------------------------------------------------------------------

def _jobs_due(jobs: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """返回当前时间到期的任务列表。

    检查条件：
    1. 任务已启用
    2. cron 表达式有效
    3. next_run 时间已到
    4. 不在错误退避期内

    Args:
        jobs: 任务列表
        now: 当前本地时间

    Returns:
        到期任务列表
    """
    due: list[dict[str, Any]] = []
    for job in jobs:
        # 跳过禁用的任务
        if not job.get("enabled", True):
            continue

        # 验证 cron 表达式
        schedule = job.get("schedule", "")
        if not validate_cron_expression(schedule):
            continue

        # 检查 next_run
        next_run_str = job.get("next_run")
        if not next_run_str:
            continue
        try:
            next_run = datetime.fromisoformat(next_run_str)
            # 兼容旧格式：移除时区信息进行比较
            if next_run.tzinfo is not None:
                next_run = next_run.replace(tzinfo=None)
        except (ValueError, TypeError):
            continue

        # 检查是否到期
        if next_run > now:
            continue

        # 检查错误退避
        consecutive_errors = job.get("consecutive_errors", 0)
        if consecutive_errors > 0:
            last_run_str = job.get("last_run")
            if last_run_str:
                try:
                    last_run = datetime.fromisoformat(last_run_str)
                    if last_run.tzinfo is not None:
                        last_run = last_run.replace(tzinfo=None)
                    backoff = _get_backoff_seconds(consecutive_errors)
                    elapsed = (now - last_run).total_seconds()
                    if elapsed < backoff:
                        continue
                except (ValueError, TypeError):
                    pass

        due.append(job)

    return due


class CronScheduler:
    """Cron 调度器。

    作为后台 asyncio 任务运行，不阻塞当前会话。
    每个 tick 检查到期任务，在独立子进程中执行。

    使用方式：
        scheduler = get_scheduler()
        await scheduler.start()   # 启动
        await scheduler.stop()    # 停止
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._shutdown = asyncio.Event()
        self._running = False

    @property
    def is_running(self) -> bool:
        """调度器是否正在运行。"""
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> None:
        """启动调度器后台任务。

        调度器作为 asyncio.Task 运行，不阻塞当前会话。
        如果已在运行则忽略。

        注意：PID 文件由守护进程入口（run_cron_serve）管理，
        此处不再写入 PID。
        """
        if self.is_running:
            logger.debug("Scheduler already running, ignoring duplicate start")
            return

        self._shutdown.clear()
        self._running = True

        # 创建后台任务
        self._task = asyncio.create_task(
            self._run_loop(),
            name="cron-scheduler",
        )
        logger.info("Cron scheduler started (tick=%ds)", TICK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """停止调度器后台任务。

        注意：PID 文件由守护进程入口（run_cron_serve）管理，
        此处不再删除 PID。
        """
        if not self.is_running:
            return

        self._shutdown.set()
        self._running = False

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        logger.info("Cron scheduler stopped")

    async def _run_loop(self) -> None:
        """调度器主循环。

        启动两个并行循环：
        - tick 循环：检查到期任务并执行（可能阻塞在委托等待上，最长 330s）
        - reap 循环：每 3s 清理一次性任务与回收领取窗口耗尽的委托任务。
          必须独立于 tick：tick 阻塞在委托等待期间，若 reap 只在 tick 之后
          执行，30s 领取窗口耗尽的委托任务要等 tick 全部完成才被回收，
          导致「窗口耗尽 → 回退子进程」退化为 330s 超时，且阻塞后续 tick
          （_MAX_CONCURRENT_JOBS=1 时其他任务全部延迟）。
        """
        # PID 由 run_cron_serve 管理，此处不再写入

        async def _reap_loop() -> None:
            """独立回收循环：与 tick 并行，保证委托任务及时回收。"""
            while not self._shutdown.is_set():
                try:
                    # 清理已完成的一次性任务
                    removed = remove_expired_jobs()
                    if removed:
                        logger.info("Cleaned up %d expired cron job(s)", len(removed))
                    # 回收领取窗口耗尽的委托任务（指定会话执行无人接管时回退子进程）
                    from illusion_forge.services.cron_delegation import reap_expired

                    reaped = reap_expired()
                    if reaped:
                        logger.info("Reaped %d unclaimed delegated job(s)", len(reaped))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("委托任务回收循环异常")
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=3.0)
                    break
                except TimeoutError:
                    pass

        reap_task = asyncio.create_task(_reap_loop(), name="cron-reap-loop")
        try:
            while not self._shutdown.is_set():
                await self._tick()

                # 等待下一个 tick 或关闭信号
                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=TICK_INTERVAL_SECONDS,
                    )
                    break
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            logger.debug("Scheduler loop cancelled")
        except Exception:
            logger.exception("Scheduler loop crashed")
        finally:
            reap_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reap_task
            self._running = False

    async def _tick(self) -> None:
        """单次调度周期：检查到期任务并执行。"""
        now = _now_local()
        jobs = load_cron_jobs()
        due = _jobs_due(jobs, now)

        if not due:
            return

        logger.info("Tick: %d job(s) due", len(due))

        # 受并发限制执行任务
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_JOBS)

        async def _run_with_limit(job: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await execute_job(job)

        # 并发执行到期任务
        results = await asyncio.gather(
            *(_run_with_limit(job) for job in due),
            return_exceptions=True,
        )

        # 记录异常
        for result in results:
            if isinstance(result, BaseException):
                logger.error("Unexpected error executing cron job: %s", result)

    def status(self) -> dict[str, Any]:
        """返回调度器状态信息。

        注意：running/pid 通过 PID 文件判断守护进程状态（跨进程一致），
        而非进程内单例状态。非 daemon 进程（如 Web 主程序）中 is_running 始终为 False，
        但 PID 文件指向存活的 daemon → running 应为 True。
        """
        jobs = load_cron_jobs()
        enabled = [j for j in jobs if j.get("enabled", True)]
        log_path = get_logs_dir() / "cron_scheduler.log"
        # 使用 PID 文件判断守护进程状态（跨进程一致）
        running = is_scheduler_running()
        pid = read_pid()
        return {
            "running": running,
            "pid": pid,
            "total_jobs": len(jobs),
            "enabled_jobs": len(enabled),
            "log_file": str(log_path),
            "history_file": str(get_history_path()),
        }


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_scheduler: CronScheduler | None = None


def get_scheduler() -> CronScheduler:
    """获取全局调度器单例。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = CronScheduler()
    return _scheduler


async def ensure_started() -> None:
    """确保调度器正在运行。如果未运行则自动启动。

    在创建 cron 任务时调用，确保调度器自动启动。
    """
    scheduler = get_scheduler()
    if not scheduler.is_running:
        await scheduler.start()


# ---------------------------------------------------------------------------
# 向后兼容的函数接口
# ---------------------------------------------------------------------------

def scheduler_status() -> dict[str, Any]:
    """返回调度器状态信息字典（向后兼容函数接口）。"""
    return get_scheduler().status()


def start_daemon() -> int:
    """启动调度器守护进程。

    .. deprecated::
        此函数为向后兼容保留。推荐使用 `maybe_spawn_cron_daemon()`。
        PID 现由 run_cron_serve 管理，此函数仅返回当前进程 PID。

    Returns:
        当前进程 PID
    """
    warnings.warn(
        "start_daemon() 已废弃，请使用 maybe_spawn_cron_daemon()",
        DeprecationWarning,
        stacklevel=2,
    )
    return os.getpid()


def stop_scheduler() -> bool:
    """停止调度器。

    .. deprecated::
        此函数为向后兼容保留。推荐使用 `kill_cron_daemon_by_pid()`。
        实际停止逻辑已移至 kill_cron_daemon_by_pid。

    Returns:
        bool: 始终返回 False（无法通过此函数停止真实守护进程）
    """
    warnings.warn(
        "stop_scheduler() 已废弃，请使用 kill_cron_daemon_by_pid()",
        DeprecationWarning,
        stacklevel=2,
    )
    return False


# 导出的公共接口
__all__ = [
    "TICK_INTERVAL_SECONDS",
    "CronScheduler",
    "append_history",
    "ensure_started",
    "execute_job",
    "get_scheduler",
    "is_scheduler_running",
    "load_history",
    "scheduler_status",
    "start_daemon",
    "stop_scheduler",
]
