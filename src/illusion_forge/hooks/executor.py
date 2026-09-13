"""
钩子执行引擎
============

实现钩子的核心执行逻辑

支持的钩子类型：
    - CommandHookDefinition: 执行 Shell 命令
    - HttpHookDefinition: 发送 HTTP 请求
    - PromptHookDefinition: 使用模型验证
    - AgentHookDefinition: 使用 Agent 深度验证
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from illusion_forge.api.client import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    SupportsStreamingMessages,
)
from illusion_forge.engine.messages import ConversationMessage
from illusion_forge.hooks.events import HookEvent
from illusion_forge.hooks.loader import HookRegistry
from illusion_forge.hooks.schemas import (
    AgentHookDefinition,
    CommandHookDefinition,
    HookMatcherDefinition,
    HttpHookDefinition,
    PromptHookDefinition,
)
from illusion_forge.hooks.types import AggregatedHookResult, HookResult
from illusion_forge.sandbox import SandboxUnavailableError
from illusion_forge.utils.http import create_async_client
from illusion_forge.utils.shell import create_shell_subprocess


@dataclass
class HookExecutionContext:
    """钩子执行上下文。"""

    cwd: Path
    api_client: SupportsStreamingMessages
    default_model: str
    session_id: str = ""
    plugin_root: Path | None = None
    plugin_data: Path | None = None


def matches_pattern(match_query: str, matcher: str) -> bool:
    """匹配模式判断。

    支持三种匹配模式：
    - 空字符串或 *：匹配所有
    - 字母数字+管道分隔：精确匹配（如 "Write|Edit"）
    - 其他：正则表达式
    """
    if not matcher or matcher == "*":
        return True
    if re.match(r'^[a-zA-Z0-9_|]+$', matcher):
        if "|" in matcher:
            patterns = [p.strip() for p in matcher.split("|")]
            return match_query in patterns
        return match_query == matcher
    try:
        return bool(re.search(matcher, match_query))
    except re.error:
        return False


def process_hook_json_output(text: str, event: HookEvent) -> dict[str, Any]:
    """解析钩子 JSON 输出。

    按 hookEventName 分发提取事件特定字段（additionalContext, updatedInput 等）。
    """
    result: dict[str, Any] = {
        "permission_behavior": None,
        "prevent_continuation": False,
        "stop_reason": None,
        "system_message": None,
        "hook_specific_output": None,
        "blocking_error": None,
        "additional_context": None,
        "updated_input": None,
        "initial_user_message": None,
        "watch_paths": None,
    }
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return result
    if not isinstance(parsed, dict):
        return result

    # continue: false
    if parsed.get("continue") is False:
        result["prevent_continuation"] = True
        result["stop_reason"] = parsed.get("stopReason")

    # decision
    decision = parsed.get("decision")
    if decision == "approve":
        result["permission_behavior"] = "allow"
    elif decision == "block":
        result["permission_behavior"] = "deny"
        result["blocking_error"] = parsed.get("reason", "hook blocked the action")

    # systemMessage
    if "systemMessage" in parsed:
        result["system_message"] = parsed["systemMessage"]

    # hookSpecificOutput — 按 hookEventName 分发
    hso = parsed.get("hookSpecificOutput")
    if isinstance(hso, dict):
        result["hook_specific_output"] = hso
        hook_event_name = hso.get("hookEventName")

        # 通用 additionalContext（大多数事件都支持）
        if "additionalContext" in hso:
            result["additional_context"] = hso["additionalContext"]

        if hook_event_name == "PreToolUse":
            pd = hso.get("permissionDecision")
            if pd == "allow":
                result["permission_behavior"] = "allow"
            elif pd == "deny":
                result["permission_behavior"] = "deny"
                result["blocking_error"] = hso.get("permissionDecisionReason", "hook denied")
            if "updatedInput" in hso:
                result["updated_input"] = hso["updatedInput"]

        elif hook_event_name == "SessionStart":
            if "initialUserMessage" in hso:
                result["initial_user_message"] = hso["initialUserMessage"]
            if "watchPaths" in hso:
                result["watch_paths"] = hso["watchPaths"]

        elif hook_event_name == "PermissionDenied":
            if hso.get("retry"):
                result["hook_specific_output"]["retry"] = True

        elif hook_event_name == "PermissionRequest":
            req_decision = hso.get("decision")
            if req_decision == "allow":
                result["permission_behavior"] = "allow"
                if "updatedInput" in hso:
                    result["updated_input"] = hso["updatedInput"]
            elif req_decision == "deny":
                result["permission_behavior"] = "deny"
                result["blocking_error"] = hso.get("message", "hook denied permission")

        elif hook_event_name == "Elicitation":
            action = hso.get("action")
            if action == "decline":
                result["permission_behavior"] = "deny"
                result["blocking_error"] = "elicitation declined by hook"

    # 兼容顶层字段（某些钩子直接输出顶层 additionalContext，无 hookSpecificOutput 包裹）
    if result["additional_context"] is None and "additionalContext" in parsed:
        result["additional_context"] = parsed["additionalContext"]
    if result["updated_input"] is None and "updatedInput" in parsed:
        result["updated_input"] = parsed["updatedInput"]
    if result["initial_user_message"] is None and "initialUserMessage" in parsed:
        result["initial_user_message"] = parsed["initialUserMessage"]
    if result["watch_paths"] is None and "watchPaths" in parsed:
        result["watch_paths"] = parsed["watchPaths"]

    return result


def _get_match_query(event: HookEvent, payload: dict[str, Any]) -> str:
    """根据事件类型从 payload 中提取匹配查询字符串。"""
    if event in (HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE, HookEvent.POST_TOOL_USE_FAILURE,
                 HookEvent.PERMISSION_DENIED, HookEvent.PERMISSION_REQUEST):
        return str(payload.get("tool_name", ""))
    elif event == HookEvent.NOTIFICATION:
        return str(payload.get("notification_type", ""))
    elif event == HookEvent.SESSION_START:
        return str(payload.get("source", ""))
    elif event == HookEvent.SESSION_END:
        return str(payload.get("reason", ""))
    elif event in (HookEvent.SUBAGENT_START, HookEvent.SUBAGENT_STOP):
        return str(payload.get("agent_type", ""))
    elif event in (HookEvent.PRE_COMPACT, HookEvent.POST_COMPACT):
        return str(payload.get("trigger", ""))
    elif event in (HookEvent.ELICITATION, HookEvent.ELICITATION_RESULT):
        return str(payload.get("mcp_server_name", ""))
    elif event == HookEvent.CONFIG_CHANGE:
        return str(payload.get("source", ""))
    elif event == HookEvent.INSTRUCTIONS_LOADED:
        return str(payload.get("load_reason", ""))
    return ""


def _inject_plugin_variables(template: str, context: HookExecutionContext) -> str:
    """替换命令中的插件变量。"""
    if context.plugin_root:
        template = template.replace("${CLAUDE_PLUGIN_ROOT}", str(context.plugin_root))
    if context.plugin_data:
        template = template.replace("${CLAUDE_PLUGIN_DATA}", str(context.plugin_data))
    template = template.replace("${CLAUDE_SESSION_ID}", context.session_id)
    return template


class HookExecutor:
    """钩子执行器。"""

    def __init__(
        self,
        registry: HookRegistry,
        context: HookExecutionContext,
        session_hook_store: Any | None = None,
    ) -> None:
        self._registry = registry
        self._context = context
        self._session_hook_store = session_hook_store

    def update_registry(self, registry: HookRegistry) -> None:
        self._registry = registry

    def update_context(
        self,
        *,
        api_client: SupportsStreamingMessages | None = None,
        default_model: str | None = None,
    ) -> None:
        if api_client is not None:
            self._context.api_client = api_client
        if default_model is not None:
            self._context.default_model = default_model

    def _get_all_hooks(self, event: HookEvent) -> list[HookMatcherDefinition]:
        """获取所有钩子（注册表 + 会话钩子）。"""
        matchers = list(self._registry.get(event))
        if self._session_hook_store is not None:
            session_matchers = self._session_hook_store.get(self._context.session_id, event)
            if isinstance(session_matchers, list):
                for sm in session_matchers:
                    matchers.append(HookMatcherDefinition(
                        matcher=getattr(sm, "matcher", ""),
                        hooks=getattr(sm, "hooks", []),
                    ))
        return matchers

    async def execute(self, event: HookEvent, payload: dict[str, Any]) -> AggregatedHookResult:
        """执行事件对应的所有匹配钩子。"""
        results: list[HookResult] = []
        match_query = _get_match_query(event, payload)

        for matcher_def in self._get_all_hooks(event):
            if not matches_pattern(match_query, matcher_def.matcher):
                continue
            for hook in matcher_def.hooks:
                if isinstance(hook, CommandHookDefinition):
                    results.append(await self._run_command_hook(hook, event, payload))
                elif isinstance(hook, HttpHookDefinition):
                    results.append(await self._run_http_hook(hook, event, payload))
                elif isinstance(hook, PromptHookDefinition):
                    results.append(await self._run_prompt_like_hook(hook, event, payload, agent_mode=False))
                elif isinstance(hook, AgentHookDefinition):
                    results.append(await self._run_prompt_like_hook(hook, event, payload, agent_mode=True))
        return AggregatedHookResult(results=results)

    async def _run_command_hook(
        self,
        hook: CommandHookDefinition,
        event: HookEvent,
        payload: dict[str, Any],
    ) -> HookResult:
        # 注入参数和插件变量
        command = _inject_arguments(hook.command, payload, shell_escape=True)
        command = _inject_plugin_variables(command, self._context)

        # 构建环境变量
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(self._context.cwd),
            "CLAUDE_SESSION_ID": self._context.session_id,
        }
        if self._context.plugin_root:
            env["CLAUDE_PLUGIN_ROOT"] = str(self._context.plugin_root)
        if self._context.plugin_data:
            env["CLAUDE_PLUGIN_DATA"] = str(self._context.plugin_data)

        timeout = hook.timeout or 30

        try:
            process = await create_shell_subprocess(
                command,
                cwd=self._context.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except SandboxUnavailableError as exc:
            return HookResult(
                hook_type=hook.type,
                success=False,
                permission_behavior="deny",
                blocking_error=str(exc),
            )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return HookResult(
                hook_type=hook.type,
                success=False,
                permission_behavior="deny",
                blocking_error=f"command hook timed out after {timeout}s",
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace").strip() if stderr else ""
        returncode = process.returncode or 0

        # 解析 JSON 输出
        json_output = process_hook_json_output(stdout_text, event)

        success = returncode == 0

        return HookResult(
            hook_type=hook.type,
            success=success,
            output=stdout_text,
            prevent_continuation=json_output["prevent_continuation"],
            permission_behavior=json_output["permission_behavior"] or ("deny" if returncode == 2 else None),
            blocking_error=json_output["blocking_error"] or (stderr_text if returncode == 2 else None),
            system_message=json_output["system_message"],
            hook_specific_output=json_output["hook_specific_output"],
            additional_context=json_output["additional_context"],
            updated_input=json_output["updated_input"],
            initial_user_message=json_output["initial_user_message"],
            watch_paths=json_output["watch_paths"],
            stop_reason=json_output["stop_reason"],
            metadata={"returncode": returncode},
        )

    async def _run_http_hook(
        self,
        hook: HttpHookDefinition,
        event: HookEvent,
        payload: dict[str, Any],
    ) -> HookResult:
        timeout = hook.timeout or 30
        try:
            async with create_async_client(timeout=timeout) as client:
                response = await client.post(
                    hook.url,
                    json=payload,
                    headers=hook.headers,
                )
            success = response.is_success
            output = response.text
            json_output = process_hook_json_output(output, event)
            return HookResult(
                hook_type=hook.type,
                success=success,
                output=output,
                permission_behavior=json_output["permission_behavior"],
                blocking_error=json_output["blocking_error"],
                system_message=json_output["system_message"],
                hook_specific_output=json_output["hook_specific_output"],
                additional_context=json_output["additional_context"],
                updated_input=json_output["updated_input"],
                initial_user_message=json_output["initial_user_message"],
                watch_paths=json_output["watch_paths"],
                stop_reason=json_output["stop_reason"],
                metadata={"status_code": response.status_code},
            )
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            return HookResult(
                hook_type=hook.type,
                success=False,
                blocking_error=str(exc),
            )

    async def _run_prompt_like_hook(
        self,
        hook: PromptHookDefinition | AgentHookDefinition,
        event: HookEvent,
        payload: dict[str, Any],
        *,
        agent_mode: bool,
    ) -> HookResult:
        prompt = _inject_arguments(hook.prompt, payload)
        prefix = (
            "You are validating whether a hook condition passes. "
            'Return strict JSON: {"ok": true} or {"ok": false, "reason": "..."}'
        )
        if agent_mode:
            prefix += " Be more thorough and reason over the payload before deciding."

        request = ApiMessageRequest(
            model=hook.model or self._context.default_model,
            messages=[ConversationMessage.from_user_text(prompt)],
            system_prompt=prefix,
            max_tokens=512,
        )

        text_chunks: list[str] = []
        final_event: ApiMessageCompleteEvent | None = None
        async for event_item in self._context.api_client.stream_message(request):  # type: ignore[attr-defined]
            if isinstance(event_item, ApiMessageCompleteEvent):
                final_event = event_item
            elif hasattr(event_item, "text"):
                text_chunks.append(event_item.text)

        text = "".join(text_chunks)
        if final_event is not None and final_event.message.text:
            text = final_event.message.text

        json_output = process_hook_json_output(text, event)
        success = json_output["permission_behavior"] != "deny" and not json_output["prevent_continuation"]
        return HookResult(
            hook_type=hook.type,
            success=success,
            output=text,
            prevent_continuation=json_output["prevent_continuation"],
            permission_behavior=json_output["permission_behavior"],
            blocking_error=json_output["blocking_error"],
            system_message=json_output["system_message"],
            hook_specific_output=json_output["hook_specific_output"],
            additional_context=json_output["additional_context"],
            updated_input=json_output["updated_input"],
            initial_user_message=json_output["initial_user_message"],
            watch_paths=json_output["watch_paths"],
            stop_reason=json_output["stop_reason"],
        )


def _inject_arguments(
    template: str, payload: dict[str, Any], *, shell_escape: bool = False
) -> str:
    """将 payload 注入到模板字符串中。"""
    serialized = json.dumps(payload, ensure_ascii=True)
    if shell_escape:
        serialized = shlex.quote(serialized)
    return template.replace("$ARGUMENTS", serialized)


def _parse_hook_json(text: str) -> dict[str, Any]:
    """解析钩子返回的 JSON 响应（向后兼容的简单格式）。"""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("ok"), bool):
            return parsed
    except json.JSONDecodeError:
        pass
    lowered = text.strip().lower()
    if lowered in {"ok", "true", "yes"}:
        return {"ok": True}
    return {"ok": False, "reason": text.strip() or "hook returned invalid JSON"}
