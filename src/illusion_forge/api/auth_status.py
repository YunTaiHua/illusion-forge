"""
认证状态查询模块
================

根据当前活跃环境的 ``api_format`` 返回简洁的认证状态字符串，
供 UI 诊断和 ``/login`` 状态展示使用。

使用示例：
    >>> from illusion_forge.api.auth_status import auth_status
    >>> from illusion_forge.config.settings import load_settings
    >>> print(auth_status(load_settings()))
"""

from __future__ import annotations

from illusion_forge.config.settings import Settings


def auth_status(settings: Settings) -> str:
    """返回简洁的认证状态字符串

    判别依据是 ``api_format``：
        - ``copilot`` / ``codex``：检查各自的 OAuth 认证状态
        - 其他（anthropic / openai）：尝试解析 api_key

    Args:
        settings: 应用设置对象

    Returns:
        str: 认证状态描述
    """
    api_format = settings.api_format

    # Copilot：认证存储在独立的 copilot_auth.json 中
    if api_format == "copilot":
        from illusion_forge.auth.copilot import CopilotAuth
        if CopilotAuth().is_authenticated():
            return "configured (copilot)"
        return "missing"

    # Codex：认证存储在独立的 codex_oauth_auth.json 中
    if api_format == "codex":
        from illusion_forge.auth.codex_oauth import CodexOAuth
        if CodexOAuth().is_authenticated():
            return "configured (codex)"
        return "missing"

    # 标准 api_key 类提供商：尝试解析认证
    try:
        settings.resolve_auth()
    except ValueError:
        return "missing"
    return "configured"
