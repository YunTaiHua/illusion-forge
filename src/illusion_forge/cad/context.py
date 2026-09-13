"""CAD 会话上下文注入（M3 协作闭环）。

每个对话轮次构建系统提示词时（illusion_forge.prompts.context），若 CAD 工作台
已启用且 SolidWorks 会话存活，把当前活动文档与用户选中项作为一段上下文
注入——用户在 SolidWorks 里选中了一个面、切换了文档，agent 下一轮立即
感知，无需调用工具自查。

本模块只读宿主的跨线程缓存字段（selection_info/state），绝不提交 STA
任务，保证提示词构建零阻塞、零 COM 调用。
"""

from __future__ import annotations


def runtime_context_section() -> str:
    """返回 CAD 会话上下文段落；未启用/未连接时返回空串。

    Returns:
        str: 形如 ``# SolidWorks Session\\n- Document: ...\\n- Selection: ...``
        的 markdown 段落；无会话时为空串（不占上下文）。
    """
    try:
        from illusion_forge.cad.host import SolidWorksHost

        host = SolidWorksHost.instance()
    except Exception:  # noqa: BLE001 — 上下文注入失败必须静默降级
        return ""
    if host._sw is None:
        return ""
    try:
        state = host.state()
        selection = host.selection_info()
        document = host.cached_document_info()
        recent = host.snapshot_history()[:3]
    except Exception:  # noqa: BLE001 — 上下文注入失败必须静默降级
        return ""

    lines: list[str] = ["# SolidWorks Session"]
    if state.get("busy_label"):
        lines.append(f"- Status: BUSY (running `{state['busy_label']}`; wait for it to finish before sending new CAD commands)")
    else:
        lines.append("- Status: idle")
    if document:
        lines.append(f"- Active document: {document.get('title') or '(unsaved)'} ({document.get('doc_type')})")
    if selection and selection.get("count"):
        items = selection.get("items") or []
        summary = ", ".join(
            f"{item.get('type')}" + (f"@{item['component']}" if item.get("component") else "")
            for item in items[:6]
        )
        more = f" (+{selection['count'] - len(items)} more)" if selection["count"] > len(items) else ""
        lines.append(
            f"- User selection ({selection['count']} object(s)): {summary}{more} — "
            "the user selected these in SolidWorks; they are likely referring to them"
        )
    if recent:
        latest = recent[0]
        lines.append(f"- Latest snapshot: {latest.get('view')} @ {latest.get('created_at')}")
    lines.append(
        "- The user may edit the model directly in SolidWorks at any time; "
        "re-run cad_session_status if the feature tree may have changed"
    )
    if len(lines) <= 2:
        return ""
    return "\n".join(lines)
