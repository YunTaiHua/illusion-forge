"""
规则斜杠命令
============

/rules — 查看项目规则
"""

from __future__ import annotations

from illusion_forge.commands.types import CommandContext, CommandResult


async def rules_handler(args: str, context: CommandContext) -> CommandResult:
    """规则命令处理器"""
    # 加载项目级权限配置
    from illusion_forge.permissions.loader import (
        filter_rules_by_permissions,
        is_rules_disabled,
        load_project_permissions,
    )
    from illusion_forge.skills.loader import get_project_rules_dir
    project_permissions = load_project_permissions(context.cwd)

    # 检查是否禁用所有 rules
    if is_rules_disabled(project_permissions):
        return CommandResult(message="All rules are disabled")

    rules_dir = get_project_rules_dir(context.cwd)
    all_rule_files = sorted(rules_dir.glob("*.md"))

    # 过滤掉被禁用的 rules
    rule_files = filter_rules_by_permissions(all_rule_files, project_permissions)

    if not rule_files:
        return CommandResult(message=f"No rules found in {rules_dir}")

    tokens = args.strip().split()

    # /rules — 列出所有规则
    if not tokens:
        lines = [f"Rules directory: {rules_dir}", ""]
        for i, path in enumerate(rule_files, 1):
            content = path.read_text(encoding="utf-8", errors="replace").strip()
            first_line = content.split("\n", 1)[0][:60] if content else "(empty)"
            lines.append(f"  {i}. {path.stem}  —  {first_line}")
        lines.append("")
        lines.append("Usage: /rules <name|number>  — view a specific rule")
        return CommandResult(message="\n".join(lines))

    # /rules <name|number> — 显示指定规则内容
    target = tokens[0]
    selected = None

    try:
        idx = int(target) - 1
        if 0 <= idx < len(rule_files):
            selected = rule_files[idx]
    except ValueError:
        pass

    if selected is None:
        for path in rule_files:
            if path.stem.lower() == target.lower():
                selected = path
                break

    if selected is None:
        return CommandResult(message=f"Rule not found: {target}. Use /rules to list available rules.")

    content = selected.read_text(encoding="utf-8", errors="replace").strip()
    return CommandResult(message=f"# {selected.stem}\n\n{content}")
