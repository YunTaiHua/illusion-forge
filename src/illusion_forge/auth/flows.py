"""
认证流程模块
============

本模块提供各种提供商类型的认证流程。

每个流程都是一个自包含的类，具有单一的 run() 方法，
执行交互式认证并返回获取的凭据。

类说明：
    - AuthFlow: 认证流程抽象基类
    - ApiKeyFlow: API 密钥认证流程

使用示例：
    >>> from illusion_forge.auth.flows import ApiKeyFlow
    >>> flow = ApiKeyFlow(prompt_text="输入 API 密钥")
    >>> key = flow.run()
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class AuthFlow(ABC):
    """认证流程抽象基类"""

    @abstractmethod
    def run(self) -> str:
        """执行流程并返回获取的凭据值"""


class ApiKeyFlow(AuthFlow):
    """提示用户输入 API 密钥（明文输入）

    Attributes:
        prompt_text: 提示文本
    """

    def __init__(self, prompt_text: str = "API Key") -> None:
        self.prompt_text = prompt_text

    def run(self) -> str:
        """提示用户输入 API 密钥

        Returns:
            str: 输入的 API 密钥

        Raises:
            ValueError: 密钥为空
        """
        key = input(f"{self.prompt_text}: ").strip()
        if not key:
            raise ValueError("Credential cannot be empty.")
        return key
