"""
退出计划模式工具
================

本模块提供退出计划权限模式的功能，允许代理在完成计划编写后请求用户审批。

主要组件：
    - ExitPlanModeTool: 退出计划模式的工具

使用示例：
    >>> from illusion_forge.tools import ExitPlanModeTool
    >>> tool = ExitPlanModeTool()
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from illusion_forge.config.i18n import t as _t
from illusion_forge.config.settings import load_settings, save_settings
from illusion_forge.permissions import PermissionMode
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult


class ExitPlanModeToolInput(BaseModel):
    """退出计划模式的输入模型。

    此工具不需要任何输入参数。计划内容从计划文件中读取。
    """


class ExitPlanModeTool(BaseTool[ExitPlanModeToolInput]):
    """退出计划模式并向用户展示计划以供审批。

    当代理在计划模式下完成计划编写后，使用此工具将计划提交给用户审批。
    工具会从计划文件中读取计划内容，暂停执行并显示给用户，
    用户可以选择批准或拒绝。批准后代理可以开始实施，
    拒绝后代理可以修改计划并重新提交。
    """

    name = "exit_plan_mode"
    description = """Use this tool when you are in plan mode and have finished writing your plan to the plan file and are ready for user approval.

## How This Tool Works
- You should have already written your plan to the plan file specified in the plan mode system message
- This tool does NOT take the plan content as a parameter - it will read the plan from the file you wrote
- This tool simply signals that you're done planning and ready for the user to review and approve
- The user will see the contents of your plan file when they review it

## When to Use This Tool
IMPORTANT: Only use this tool when the task requires planning the implementation steps of a task that requires writing code. For research tasks where you're gathering information, searching files, reading files or in general trying to understand the codebase - do NOT use this tool.

## Before Using This Tool
Ensure your plan is complete and unambiguous:
- If you have unresolved questions about requirements or approach, use AskUserQuestion first (in earlier phases)
- Once your plan is finalized, use THIS tool to request approval

**Important:** Do NOT use AskUserQuestion to ask "Is this plan okay?" or "Should I proceed?" - that's exactly what THIS tool does. ExitPlanMode inherently requests user approval of your plan.

## Examples

1. Initial task: "Search for and understand the implementation of vim mode in the codebase" - Do not use the exit plan mode tool because you are not planning the implementation steps of a task.
2. Initial task: "Help me implement yank mode for vim" - Use the exit plan mode tool after you have finished planning the implementation steps of the task.
3. Initial task: "Add a new feature to handle user authentication" - If unsure about auth method (OAuth, JWT, etc.), use AskUserQuestion first, then use exit plan mode tool after clarifying the approach."""
    input_model = ExitPlanModeToolInput

    async def execute(self, arguments: ExitPlanModeToolInput, context: ToolExecutionContext) -> ToolResult:
        del arguments

        from illusion_forge.config.plan_file import DEFAULT_SESSION_ID, get_plan, get_plan_file_path

        # 1. 读取计划文件
        plan_content = get_plan(DEFAULT_SESSION_ID)
        if not plan_content:
            return ToolResult(
                output="No plan file found. Write your plan to the plan file first.",
                is_error=True,
            )

        # 2. 获取计划文件路径（用于退出消息引用）
        plan_path = get_plan_file_path(DEFAULT_SESSION_ID)

        # 3. 恢复权限模式（恢复到进入计划模式之前的模式）
        settings = load_settings()
        checker = context.metadata.get("permission_checker")
        if checker:
            checker.restore_mode()
            settings.permission.mode = checker.current_mode
        else:
            settings.permission.mode = PermissionMode.DEFAULT
        save_settings(settings)

        # 4. 调用审批回调
        plan_approval_prompt: Any = context.metadata.get("plan_approval_prompt")
        if not callable(plan_approval_prompt):
            # 无审批回调时直接返回成功（非交互模式兼容）
            return ToolResult(
                output=f"Permission mode restored (no approval UI available). Plan file: {plan_path}"
            )

        # 5. 将计划内容推入卡片展示，等待用户审批
        approved, feedback = await plan_approval_prompt(plan_content)  # pyright: ignore[reportGeneralTypeIssues]

        # 检测无头（print）模式跨轮次审批标记
        from illusion_forge.ui.headless_prompts import PENDING_PLAN_APPROVAL_MARKER
        if feedback == PENDING_PLAN_APPROVAL_MARKER:
            # 无头模式：计划已持久化，等待下一轮审批
            # 不重新进入计划模式（模式已在步骤 3 恢复）
            return ToolResult(output=PENDING_PLAN_APPROVAL_MARKER)

        if approved:
            return ToolResult(
                output=(
                    "Plan approved. Starting implementation.\n\n"
                    "Exited plan mode. You can now make edits, run tools, and take actions. "
                    f"The plan file is located at {plan_path} if you need to reference it."
                )
            )
        else:
            # 用户拒绝：切回计划模式，重新注册计划文件路径以便继续修改
            settings = load_settings()
            settings.permission.mode = PermissionMode.PLAN
            save_settings(settings)
            if checker:
                checker.set_mode(PermissionMode.PLAN)
                checker.set_plan_file(plan_path)
            reason = feedback or _t("User rejected the plan.")
            return ToolResult(output=reason, is_error=True)
