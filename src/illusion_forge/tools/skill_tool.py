"""
技能内容读取工具
================

本模块提供读取已加载技能内容的功能。
支持 frontmatter 字段（hooks 注册、变量替换等）。
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field, ValidationError

from illusion_forge.skills.loader import load_skill_registry
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class SkillToolInput(BaseModel):
    """技能查找参数。"""

    name: str = Field(description="Skill name")
    args: str | None = Field(default=None, description="Optional arguments for the skill")


class SkillTool(BaseTool[SkillToolInput]):
    """返回已加载技能的内容。

    支持：
    - frontmatter 字段（allowed_tools, model, hooks, context 等）
    - $ARGUMENTS 变量替换
    - ${CLAUDE_PLUGIN_ROOT} 等插件变量替换
    - 技能钩子注册到会话
    """

    name = "skill"
    description = """Load a skill's instructions so you can then execute them yourself.

This tool does NOT execute anything — it only returns the skill's content (instructions, workflows, examples). You must read the returned content and follow it step by step to complete the task.

When users ask you to perform tasks, check if any of the available skills match. Skills provide specialized capabilities and domain knowledge.

When users reference a "slash command" or "/<something>" (e.g., "/<skill-name>"), they are referring to a skill. Use this tool to load its instructions.

How to use:
- Call this tool with the skill name and optional arguments
- The tool returns the skill's instructions — you then execute them

Important:
- Available skills are listed in <system-reminder> messages in the conversation
- When a skill matches the user's request, this is a BLOCKING REQUIREMENT: call this Skill tool to load its instructions BEFORE generating any other response about the task
- NEVER mention a skill without actually calling this tool
- Do not load a skill that is already active in the current context
- Do not use this tool for built-in CLI commands (like /help, /clear, etc.)
- If you see a <command-name> tag in the current conversation turn, the skill's instructions have ALREADY been loaded — follow the instructions directly instead of calling this tool again"""
    input_model = SkillToolInput

    def is_read_only(self, arguments: SkillToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: SkillToolInput, context: ToolExecutionContext) -> ToolResult:
        # 加载技能注册表（涉及大量文件 I/O，委托给线程池避免阻塞事件循环）
        registry = await asyncio.to_thread(load_skill_registry, context.cwd)
        # 尝试多种名称格式匹配
        skill = (
            registry.get(arguments.name)
            or registry.get(arguments.name.lower())
            or registry.get(arguments.name.title())
            or registry.get(arguments.name.replace("-", "_"))
            or registry.get(arguments.name.replace("_", "-"))
        )
        if skill is None:
            return ToolResult(output=f"Skill not found: {arguments.name}", is_error=True)

        content = skill.content

        # 变量替换
        if arguments.args and "$ARGUMENTS" in content:
            content = content.replace("$ARGUMENTS", arguments.args)

        # 插件变量替换
        if skill.skill_root:
            content = content.replace("${CLAUDE_PLUGIN_ROOT}", skill.skill_root)
            content = content.replace("${CLAUDE_SKILL_DIR}", skill.skill_root)

        # 注册技能钩子到会话（如果有的话）
        if skill.hooks:
            try:
                from illusion_forge.hooks.register_hooks import register_skill_hooks
                session_id = context.metadata.get("session_id", "")
                if session_id:
                    from illusion_forge.hooks.schemas import (
                        HookMatcherDefinition,
                        parse_hook_definition,
                    )
                    from illusion_forge.hooks.session_hooks import SessionHookStore
                    # 将 skill.hooks 转换为 HookMatcherDefinition 格式
                    hooks_settings = {}
                    for event_name, matchers_data in skill.hooks.items():
                        matchers = []
                        for m in matchers_data:
                            if isinstance(m, dict):
                                hook_list = []
                                for h in m.get("hooks", []):
                                    if isinstance(h, dict):
                                        try:
                                            hook_list.append(parse_hook_definition(h))
                                        except ValueError:
                                            continue
                                matchers.append(HookMatcherDefinition(
                                    matcher=m.get("matcher", ""),
                                    hooks=hook_list,
                                ))
                        hooks_settings[event_name] = matchers
                    store = context.metadata.get("session_hook_store")
                    if store and isinstance(store, SessionHookStore):
                        register_skill_hooks(store, session_id, hooks_settings, skill.name, skill.skill_root)
            except (ImportError, ValidationError, ValueError, TypeError, AttributeError, KeyError):
                logger.debug("[skill_tool] Hook registration failed for skill %s", skill.name, exc_info=True)

        return ToolResult(output=content)
