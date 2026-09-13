"""
进入工作树工具
=============

本模块提供创建和进入 git 工作树的功能，用于隔离开发环境。

主要组件：
    - EnterWorktreeTool: 创建并进入 git 工作树的工具

使用示例：
    >>> from illusion_forge.tools import EnterWorktreeTool
    >>> tool = EnterWorktreeTool()
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from illusion_forge.config.settings import load_settings
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult


class EnterWorktreeToolInput(BaseModel):
    """进入工作树参数。

    属性：
        name: 工作树名称（可选，不提供则生成随机名称）
    """

    name: str | None = Field(
        default=None,
        description="A name for the worktree. If not provided, a random name is generated.",
    )


class EnterWorktreeTool(BaseTool[EnterWorktreeToolInput]):
    """创建 git 工作树。

    仅在用户明确要求使用工作树时使用。此工具创建隔离的 git 工作树并切换当前会话到其中。
    """

    name = "enter_worktree"
    description = """Use this tool ONLY when the user explicitly asks to work in a worktree. This tool creates an isolated git worktree and switches the current session into it.

## When to Use

- The user explicitly says "worktree" (e.g., "start a worktree", "work in a worktree", "create a worktree", "use a worktree")

## When NOT to Use

- The user asks to create a branch, switch branches, or work on a different branch -- use git commands instead
- The user asks to fix a bug or work on a feature -- use normal git workflow unless they specifically mention worktrees
- Never use this tool unless the user explicitly mentions "worktree"

## Requirements

- Must be in a git repository, OR have WorktreeCreate/WorktreeRemove hooks configured in settings.json
- Must not already be in a worktree

## Behavior

- In a git repository: creates a new git worktree inside `.illusion/worktrees/` with a new branch based on HEAD
- Outside a git repository: delegates to WorktreeCreate/WorktreeRemove hooks for VCS-agnostic isolation
- Switches the session's working directory to the new worktree
- Use ExitWorktree to leave the worktree mid-session (keep or remove). On session exit, if still in the worktree, the user will be prompted to keep or remove it

## Parameters

- `name` (optional): A name for the worktree. If not provided, a random name is generated."""
    input_model = EnterWorktreeToolInput

    async def execute(
        self,
        arguments: EnterWorktreeToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        name = arguments.name or f"wt-{uuid4().hex[:8]}"

        # 检查是否已在 worktree 中
        if _is_in_worktree(context.cwd):
            return ToolResult(
                output="Already in a worktree session. Use exit_worktree to leave first.",
                is_error=True,
            )

        branch_name = name

        # 尝试 git 仓库路径
        top_level = await _git_output(context.cwd, "rev-parse", "--show-toplevel")
        if top_level is not None:
            # ---- Git 仓库模式 ----
            repo_root = Path(top_level)
            worktree_path = _resolve_worktree_path(repo_root, branch_name)
            await asyncio.to_thread(worktree_path.parent.mkdir, parents=True, exist_ok=True)
            cmd = ["git", "worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"]
            proc = await _create_git_subprocess(cmd, cwd=repo_root)
            try:
                stdout_bytes, stderr_bytes = await proc.communicate()
            except asyncio.CancelledError:
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    pass
                with contextlib.suppress(Exception):
                    await proc.wait()
                raise
            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
            output = (stdout or stderr).strip() or f"Created worktree {worktree_path}"
            if proc.returncode != 0:
                return ToolResult(output=output, is_error=True)
            return ToolResult(
                output=f"{output}\nPath: {worktree_path}",
                metadata={"new_cwd": str(worktree_path)},
            )
        else:
            # ---- 非 Git 仓库：检查 WorktreeCreate/WorktreeRemove hooks ----
            settings = load_settings()
            hooks = settings.hooks or {}
            has_create = "WorktreeCreate" in hooks or "worktree_create" in hooks
            has_remove = "WorktreeRemove" in hooks or "worktree_remove" in hooks
            if has_create and has_remove:
                worktree_path = _resolve_worktree_path(context.cwd.resolve(), branch_name)
                await asyncio.to_thread(worktree_path.mkdir, parents=True, exist_ok=True)
                return ToolResult(
                    output=f"Created isolated worktree at {worktree_path}",
                    metadata={"new_cwd": str(worktree_path)},
                )
            return ToolResult(
                output=(
                    "enter_worktree requires a git repository "
                    "or WorktreeCreate/WorktreeRemove hooks configured in settings.json"
                ),
                is_error=True,
            )


async def _create_git_subprocess(
    cmd: list[str],
    cwd: Path,
) -> asyncio.subprocess.Process:
    """创建 git 子进程，跨平台处理 Windows 的 CREATE_NO_WINDOW 标志。"""
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return await asyncio.create_subprocess_exec(*cmd, **kwargs)


async def _git_output(cwd: Path, *args: str) -> str | None:
    """执行 git 命令并返回输出。

    参数：
        cwd: 工作目录
        *args: git 命令参数

    返回：
        命令输出字符串，失败返回 None
    """
    proc = await _create_git_subprocess(["git", *args], cwd=cwd)
    try:
        stdout_bytes, _ = await proc.communicate()
    except asyncio.CancelledError:
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
        with contextlib.suppress(Exception):
            await proc.wait()
        raise
    if proc.returncode != 0:
        return None
    return (stdout_bytes or b"").decode("utf-8", errors="replace").strip()


def _resolve_worktree_path(repo_root: Path, name: str) -> Path:
    """解析工作树路径。

    参数：
        repo_root: 仓库根目录
        name: 工作树名称

    返回：
        解析后的工作树路径
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "worktree"
    return (repo_root / ".illusion" / "worktrees" / slug).resolve()


def _is_in_worktree(cwd: Path) -> bool:
    """检查当前工作目录是否已在 worktree 中。

    参数：
        cwd: 当前工作目录

    返回：
        是否已在 worktree 中
    """
    cwd_str = str(cwd.resolve())
    return "/.illusion/worktrees/" in cwd_str.replace("\\", "/")
