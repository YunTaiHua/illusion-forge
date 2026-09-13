"""
使用量追踪模块
==============

本模块提供 API 使用量追踪的数据模型。

主要功能：
    - 记录输入/输出令牌数
    - 记录缓存命中/写入令牌数
    - 计算完整输入和上下文大小

类说明：
    - UsageSnapshot: 模型提供商返回的使用量快照

使用示例：
    >>> from illusion_forge.api.usage import UsageSnapshot
    >>> usage = UsageSnapshot(input_tokens=1000, output_tokens=500)
    >>> print(f"总令牌数: {usage.total_tokens}")
"""

from __future__ import annotations

from pydantic import BaseModel


class UsageSnapshot(BaseModel):
    """模型提供商返回的令牌使用量

    记录一次 API 调用消耗的输入和输出令牌数量。

    Attributes:
        input_tokens: 非缓存输入令牌数量（计费，默认 0）
        output_tokens: 输出令牌数量（默认 0）
        cache_read_input_tokens: 缓存命中令牌数量（默认 0）
        cache_creation_input_tokens: 缓存写入令牌数量（Anthropic 专有，默认 0）
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """返回总令牌数量

        Returns:
            int: 输入令牌与输出令牌之和
        """
        return self.input_tokens + self.output_tokens

    @property
    def total_input_tokens(self) -> int:
        """完整输入 = 非缓存 + 缓存命中 + 缓存写入

        Returns:
            int: 该次 API 调用发送的完整输入令牌数
        """
        return (
            self.input_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )

    @property
    def context_size(self) -> int:
        """该次 API 调用时的完整上下文 = 全部输入 + 输出

        Returns:
            int: 该次 API 调用时的上下文窗口占用
        """
        return self.total_input_tokens + self.output_tokens
