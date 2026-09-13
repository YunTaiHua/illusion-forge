"""
钩子配置模式定义
================

定义钩子的配置数据模型

支持的钩子类型：
    - CommandHookDefinition: 执行 Shell 命令
    - PromptHookDefinition: 使用模型验证条件
    - HttpHookDefinition: 发送 HTTP 请求
    - AgentHookDefinition: 使用 Agent 深度验证

新增结构：
    - HookMatcherDefinition: 带 matcher 的钩子组
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field


class CommandHookDefinition(BaseModel):
    """命令钩子定义。"""

    type: Literal["command"] = "command"
    command: str
    if_field: str | None = Field(default=None, alias="if")
    shell: Literal["bash", "powershell"] | None = None
    timeout: int | None = None
    status_message: str | None = Field(default=None, alias="statusMessage")
    once: bool | None = None
    async_: bool | None = Field(default=None, alias="async")
    async_rewake: bool | None = Field(default=None, alias="asyncRewake")
    matcher: str | None = None

    model_config = {"populate_by_name": True}


class PromptHookDefinition(BaseModel):
    """提示词钩子定义。"""

    type: Literal["prompt"] = "prompt"
    prompt: str
    if_field: str | None = Field(default=None, alias="if")
    timeout: int | None = None
    model: str | None = None
    status_message: str | None = Field(default=None, alias="statusMessage")
    once: bool | None = None
    matcher: str | None = None

    model_config = {"populate_by_name": True}


class HttpHookDefinition(BaseModel):
    """HTTP 钩子定义。"""

    type: Literal["http"] = "http"
    url: str
    if_field: str | None = Field(default=None, alias="if")
    timeout: int | None = None
    headers: dict[str, str] | None = None
    allowed_env_vars: list[str] | None = Field(default=None, alias="allowedEnvVars")
    status_message: str | None = Field(default=None, alias="statusMessage")
    once: bool | None = None
    matcher: str | None = None

    model_config = {"populate_by_name": True}


class AgentHookDefinition(BaseModel):
    """Agent 钩子定义。"""

    type: Literal["agent"] = "agent"
    prompt: str
    if_field: str | None = Field(default=None, alias="if")
    timeout: int | None = None
    model: str | None = None
    status_message: str | None = Field(default=None, alias="statusMessage")
    once: bool | None = None
    matcher: str | None = None

    model_config = {"populate_by_name": True}


HookDefinition = (
    CommandHookDefinition
    | PromptHookDefinition
    | HttpHookDefinition
    | AgentHookDefinition
)


@dataclass
class HookMatcherDefinition:
    """带 matcher 的钩子组。

    格式：{ matcher?: string, hooks: HookCommand[] }
    在配置中表示为：{ "PreToolUse": [{ "matcher": "Bash", "hooks": [...] }] }
    """

    matcher: str = ""
    hooks: list[HookDefinition] = field(default_factory=list)


def parse_hook_definition(data: dict[str, Any]) -> HookDefinition:
    """从字典解析钩子定义。

    Args:
        data: 包含 type 字段的钩子定义字典

    Returns:
        解析后的钩子定义对象

    Raises:
        ValueError: 未知的钩子类型
    """
    hook_type = data.get("type")
    if hook_type == "command":
        return CommandHookDefinition.model_validate(data)
    elif hook_type == "prompt":
        return PromptHookDefinition.model_validate(data)
    elif hook_type == "http":
        return HttpHookDefinition.model_validate(data)
    elif hook_type == "agent":
        return AgentHookDefinition.model_validate(data)
    raise ValueError(f"Unknown hook type: {hook_type}")
