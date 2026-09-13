"""
认证模块
========

本模块提供 IllusionForge 统一的认证管理功能。

主要组件：
    - AuthManager: 认证管理器
    - ApiKeyFlow: API 密钥认证流程
    - store_env_credential/load_env_credential: 凭据存储/加载（按 env_N）
    - encrypt/decrypt: 加密/解密功能

使用示例：
    >>> from illusion_forge.auth import AuthManager, ApiKeyFlow
    >>> manager = AuthManager()
    >>> flow = ApiKeyFlow(prompt_text="输入 API 密钥")
    >>> key = flow.run()
"""

from illusion_forge.auth.flows import ApiKeyFlow
from illusion_forge.auth.manager import AuthManager
from illusion_forge.auth.storage import (
    clear_env_credentials,
    decrypt,
    encrypt,
    load_env_credential,
    store_env_credential,
)

__all__ = [
    "ApiKeyFlow",
    "AuthManager",
    "clear_env_credentials",
    "decrypt",
    "encrypt",
    "load_env_credential",
    "store_env_credential",
]
