"""
API 模块
========

本模块提供 IllusionForge 与各种 LLM 提供商的 API 集成。

主要组件：
    - AnthropicApiClient: Anthropic API 客户端
    - OpenAICompatibleClient: OpenAI 兼容 API 客户端
    - CodexApiClient: OpenAI Codex 客户端
    - ResponsesApiClient: 通用 OpenAI Responses API 客户端
    - IllusionForgeApiError: API 异常基类
    - UsageSnapshot: 使用量追踪

使用示例：
    >>> from illusion_forge.api import AnthropicApiClient
    >>> client = AnthropicApiClient(api_key="sk-...")
"""

from illusion_forge.api.auth_status import auth_status
from illusion_forge.api.client import AnthropicApiClient
from illusion_forge.api.codex_client import CodexApiClient
from illusion_forge.api.errors import IllusionForgeApiError
from illusion_forge.api.openai_client import OpenAICompatibleClient
from illusion_forge.api.responses_client import ResponsesApiClient
from illusion_forge.api.usage import UsageSnapshot

__all__ = [
    "AnthropicApiClient",
    "CodexApiClient",
    "IllusionForgeApiError",
    "OpenAICompatibleClient",
    "ResponsesApiClient",
    "UsageSnapshot",
    "auth_status",
]
