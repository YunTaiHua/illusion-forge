"""
无头模式交互回调模块
====================

为 print（无头）模式提供非交互的问答/审批回调：所有需要用户介入的场景
都不会阻塞等待输入，而是把请求持久化到会话目录并返回特殊标记，让本轮
执行以退出码 2 结束；调用方下一次以 `illusion-forge -c -p "<回复>"` 恢复时，
回复会被注入到对应的 tool_result 中继续执行（见 headless.run_print_mode）。

cron 守护进程即通过 `illusion-forge -p` 子进程执行任务，依赖本模块保证任务在
没有任何 TTY 的环境下也能完整跑完或干净地挂起。

主要组件：
    - PENDING_*_MARKER: 挂起标记常量（存入消息历史用于恢复定位）
    - format_question_options: 结构化问题选项 → 纯文本（渠道与无头模式共用）
    - make_print_mode_ask_user: ask_user_question 回调工厂
    - make_print_mode_plan_approval: exit_plan_mode 审批回调工厂
    - make_print_mode_permission: 工具权限回调工厂
    - make_print_mode_sandbox_permission: 沙箱权限回调工厂
"""

from __future__ import annotations

import os
import sys
from typing import Any

from illusion_forge.config.i18n import t

# ask_user_question 返回的特殊标记：作为 tool_result 存储在消息历史中，
# 恢复时用于定位待回答的问题
PENDING_ANSWER_MARKER = "__PENDING_ANSWER__"

# exit_plan_mode 返回的特殊标记：作为 tool_result 存储在消息历史中，
# 恢复时用于定位待审批的计划
PENDING_PLAN_APPROVAL_MARKER = "__PENDING_PLAN_APPROVAL__"

# 权限请求标记（state flag 用，非 tool_result）
PENDING_PERMISSION_MARKER = "__PENDING_PERMISSION__"


def format_question_options(questions: object) -> str:
    """将结构化问题选项格式化为纯文本

    questions 结构：list[dict]，每个 dict 含：
        - question: str 子问题文本
        - header: str 标题
        - options: list[dict] 选项列表，每项含 label/description
        - multiSelect: bool 是否多选
        - noCustomInput: bool 是否禁止自定义输入

    Args:
        questions: 结构化问题数据

    Returns:
        str: 格式化后的选项文本，无选项返回空串
    """
    if not isinstance(questions, (list, tuple)):
        return ""
    lines: list[str] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        opts = q.get("options") or []
        if not opts:
            continue
        header = str(q.get("header") or "").strip()
        sub_q = str(q.get("question") or "").strip()
        if header:
            lines.append(t("question_header_format").format(header=header))
        if sub_q:
            lines.append(sub_q)
        for opt in opts:
            if not isinstance(opt, dict):
                continue
            label = str(opt.get("label") or "").strip()
            desc = str(opt.get("description") or "").strip()
            if label:
                lines.append(f"  • {label}" + (f" — {desc}" if desc else ""))
    return "\n".join(lines)


def _question_item_to_dict(q: Any) -> dict[str, Any]:
    """将 QuestionItem 对象转为 dict（用于持久化）"""
    if hasattr(q, "model_dump"):
        return dict(q.model_dump(mode="json"))
    if isinstance(q, dict):
        return q
    return {"question": str(q)}


def make_print_mode_ask_user(
    *,
    cwd: str,
    session_id: str | None,
    state: dict[str, Any],
) -> Any:
    """构造 print 模式非交互 ask_user_question 回调

    回调行为：
        1. 持久化问题到 pending-question 文件
        2. 设置 state["pending_question_raised"] = True
        3. 返回 PENDING_ANSWER_MARKER 作为 tool_result

    agent 收到该标记后会结束当前轮次，run_print_mode 检测到
    state["pending_question_raised"] 后以退出码 2 退出。
    下次 illusion-forge -c -p "答案" 恢复时，答案会注入为 tool_result。

    Args:
        cwd: 工作目录
        session_id: 会话 ID
        state: 共享状态字典（用于通知 run_print_mode）

    Returns:
        ask_user_prompt 回调函数
    """

    async def _ask(question: str, questions: object = None) -> str:
        # 持久化问题
        if session_id:
            from illusion_forge.services.session_storage import save_pending_question
            questions_list = (
                [q if isinstance(q, dict) else _question_item_to_dict(q) for q in questions]
                if isinstance(questions, (list, tuple))
                else []
            )
            save_pending_question(
                cwd=cwd,
                session_id=session_id,
                tool_use_id="",  # 恢复时从消息历史中定位，不需要显式记录
                questions=questions_list,
                question_text=question,
            )
        # 通知 run_print_mode
        state["pending_question_raised"] = True
        # 输出问题到 stderr（text 模式）供调用方查看
        print(t("print_mode_question_asked"), file=sys.stderr)
        print(question, file=sys.stderr)
        if questions:
            opts_text = format_question_options(questions)
            if opts_text:
                print(opts_text, file=sys.stderr)
            # 多问题时，提示 JSON 回答格式
            if isinstance(questions, (list, tuple)) and len(questions) > 1:
                headers = [
                    str(q.get("header", "")) for q in questions
                    if isinstance(q, dict) and q.get("header")
                ]
                if headers:
                    example_pairs = [f'"{h}": "<选择>"' for h in headers]
                    example = "{" + ", ".join(example_pairs) + "}"
                    print(t("print_mode_multi_question_format").format(example=example), file=sys.stderr)
        # 返回特殊标记，作为 tool_result 存储
        return PENDING_ANSWER_MARKER

    return _ask


def make_print_mode_plan_approval(
    *,
    cwd: str,
    session_id: str | None,
    state: dict[str, Any],
) -> Any:
    """构造 print 模式非交互 plan_approval_prompt 回调

    回调行为：
        1. 持久化计划内容到 pending-plan-approval 文件
        2. 设置 state["pending_plan_approval_raised"] = True
        3. 不输出计划内容到 stderr（agent 自行用 read 工具读计划文件）
        4. 返回 (False, PENDING_PLAN_APPROVAL_MARKER) 让 exit_plan_mode
           返回包含标记的 ToolResult

    agent 收到标记后会结束当前轮次，run_print_mode 检测到
    state["pending_plan_approval_raised"] 后以退出码 2 退出。
    下次 illusion-forge -c -p "批准" 恢复时，审批结果会注入为 tool_result。

    Args:
        cwd: 工作目录
        session_id: 会话 ID
        state: 共享状态字典（用于通知 run_print_mode）

    Returns:
        plan_approval_prompt 回调函数，签名为 async (plan: str) -> tuple[bool, str]
    """
    from illusion_forge.config.plan_file import DEFAULT_SESSION_ID, get_plan_file_path

    async def _approve(plan: str) -> tuple[bool, str]:
        plan_path = str(get_plan_file_path(DEFAULT_SESSION_ID))
        # 持久化计划内容
        if session_id:
            from illusion_forge.services.session_storage import save_pending_plan_approval
            save_pending_plan_approval(
                cwd=cwd,
                session_id=session_id,
                plan=plan,
                plan_path=plan_path,
            )
        # 通知 run_print_mode
        state["pending_plan_path"] = plan_path
        state["pending_plan_approval_raised"] = True
        # 返回 pending 标记，exit_plan_mode 会返回包含标记的 ToolResult
        return (False, PENDING_PLAN_APPROVAL_MARKER)

    return _approve


def make_print_mode_permission(
    *,
    cwd: str,
    session_id: str | None,
    state: dict[str, Any],
) -> Any:
    """print 模式跨轮次权限确认回调工厂

    检查顺序：
    1. pending-permission 文件 approved=true（Y 一次性允许，用完即删）
    2. 未命中：持久化请求 + 设置 state flag + 返回 False

    Args:
        cwd: 工作目录路径
        session_id: 会话 ID（None 时不持久化）
        state: print 模式状态字典（设置 pending_permission_raised flag）

    Returns:
        权限回调函数 (tool_name, reason) -> bool
    """
    from illusion_forge.services.session_storage import (
        delete_pending_permission,
        load_pending_permission,
        save_pending_permission,
    )

    async def _prompt(tool_name: str, reason: str, high_risk: bool = False) -> bool:
        # cron 投递任务（ILLUSION_CRON_AUTO_APPROVE=1）：自动批准所有工具权限
        #（含高危），对齐渠道端 `_make_permission_prompt` 行为。保留沙箱限制，
        # 沙箱确认不受此影响（由 make_print_mode_sandbox_permission 处理）。
        if os.environ.get("ILLUSION_CRON_AUTO_APPROVE") == "1":
            return True
        # 1. 一次性允许（pending 文件 approved=true）
        if session_id:
            pending = load_pending_permission(cwd, session_id)
            if pending and pending.get("tool_name") == tool_name and pending.get("approved"):
                delete_pending_permission(cwd, session_id)  # 一次性，用完即删
                return True
            # 2. 未命中：持久化请求
            save_pending_permission(
                cwd=cwd, session_id=session_id, tool_name=tool_name, reason=reason
            )
        state["pending_permission_tool"] = tool_name
        state["pending_permission_raised"] = True
        return False

    return _prompt


def make_print_mode_sandbox_permission(
    *,
    cwd: str,
    session_id: str | None,
    state: dict[str, Any],
) -> Any:
    """print 模式沙箱权限两选项（允许/拒绝）跨轮次确认回调工厂

    与通用 `make_print_mode_permission`（Y/N 两选项）不同，print 模式的沙箱
    权限确认仅提供两选项（允许/拒绝），使用独立的 pending-sandbox 文件实现
    跨轮次退出：

    1. 首次拦截：持久化 pending-sandbox 文件，设置 state flag，返回 False
    2. 用户 `-c -p "Y"`（允许）：run_print_mode 置 approved=true，回调放行并删除
    3. 用户 `-c -p "N"`（拒绝）：run_print_mode 删除 pending，回调返回 False

    沙箱拒绝为一次性放行，不提供"永久允许"（始终允许）选项，避免把"已放行
    某次访问"误用作后续所有相同路径操作的通行证。

    Args:
        cwd: 工作目录路径
        session_id: 会话 ID（None 时不持久化）
        state: print 模式状态字典（设置 pending_sandbox_raised flag）

    Returns:
        沙箱权限回调函数 (tool_name, reason) -> bool
    """
    from illusion_forge.services.session_storage import (
        delete_pending_sandbox,
        load_pending_sandbox,
        save_pending_sandbox,
    )

    async def _prompt(tool_name: str, reason: str, high_risk: bool = False) -> bool:
        # 一次性允许（pending-sandbox 文件 approved=true，用完即删）
        if session_id:
            pending = load_pending_sandbox(cwd, session_id)
            if pending and pending.get("tool_name") == tool_name and pending.get("approved"):
                delete_pending_sandbox(cwd, session_id)
                return True
            # 未命中：持久化请求
            save_pending_sandbox(
                cwd=cwd, session_id=session_id, tool_name=tool_name, reason=reason
            )
        state["pending_sandbox_tool"] = tool_name
        state["pending_sandbox_raised"] = True
        return False

    return _prompt
