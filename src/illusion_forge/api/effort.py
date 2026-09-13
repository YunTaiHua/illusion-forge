"""
Effort 级别管理模块
===================

本模块提供 effort（推理强度）级别的管理和映射功能。

主要功能：
    - EffortLevel 枚举：定义所有支持的 effort 级别
    - EffortMapper 类：管理 effort 级别的映射和降级

使用示例：
    >>> from illusion_forge.api.effort import EffortLevel, EffortMapper
    >>> effort = EffortMapper.normalize("high")
    >>> fallback = EffortMapper.fallback(effort, {EffortLevel.HIGH})
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar


class EffortLevel(str, Enum):
    """Effort 级别枚举

    定义所有支持的 effort（推理强度）级别。

    Attributes:
        LOW: 低强度，最快响应
        MEDIUM: 中等强度，平衡推理
        HIGH: 高强度，最深推理
        XHIGH: 超高强度，比 high 更深的推理
        MAX: 最大强度，最大推理深度
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class EffortMapper:
    """Effort 级别映射器

    管理 effort 级别的映射和降级逻辑。

    类属性：
        SUPPORTED_LEVELS: 支持的 effort 级别集合
        FALLBACK_MAP: 降级映射表
        REVERSE_MAP: 反向映射表
    """

    # 支持的 effort 级别（默认支持 low/medium/high）
    SUPPORTED_LEVELS: ClassVar[set[EffortLevel]] = {
        EffortLevel.LOW,
        EffortLevel.MEDIUM,
        EffortLevel.HIGH,
    }

    # 降级映射表：当模型不支持当前级别时，按优先级尝试的级别列表
    FALLBACK_CHAIN: ClassVar[dict[EffortLevel, list[EffortLevel]]] = {
        EffortLevel.LOW: [EffortLevel.HIGH],
        EffortLevel.MEDIUM: [EffortLevel.HIGH],
        EffortLevel.HIGH: [EffortLevel.HIGH],
        EffortLevel.XHIGH: [EffortLevel.MAX, EffortLevel.HIGH],
        EffortLevel.MAX: [EffortLevel.XHIGH, EffortLevel.HIGH],
    }

    @classmethod
    def normalize(cls, effort: str | EffortLevel) -> EffortLevel:
        """标准化 effort 级别

        将字符串或 EffortLevel 对象标准化为 EffortLevel 枚举值。

        Args:
            effort: effort 级别字符串或 EffortLevel 对象

        Returns:
            EffortLevel: 标准化后的 EffortLevel 枚举值

        Raises:
            ValueError: 当字符串不是有效的 effort 级别时
        """
        if isinstance(effort, str):
            return EffortLevel(effort.lower())
        return effort

    @classmethod
    def fallback(cls, effort: EffortLevel, supported_levels: set[EffortLevel]) -> EffortLevel:
        """当模型不支持当前 effort 级别时，返回降级后的级别

        支持链式降级：如果第一个降级目标也不支持，继续尝试下一个。

        Args:
            effort: 当前 effort 级别
            supported_levels: 模型支持的 effort 级别集合

        Returns:
            EffortLevel: 降级后的 effort 级别
        """
        if effort in supported_levels:
            return effort
        # 按优先级尝试降级
        for fallback_effort in cls.FALLBACK_CHAIN.get(effort, [EffortLevel.HIGH]):
            if fallback_effort in supported_levels:
                return fallback_effort
        # 所有降级都失败，返回 high 作为最终兜底
        return EffortLevel.HIGH

    @classmethod
    def reverse_fallback(cls, effort: EffortLevel) -> EffortLevel:
        """反向降级：将高级别映射到低级别

        当模型不支持高级别时，反向映射到低级别。
        对于 LOW/MEDIUM/HIGH 等基础级别，返回原值不做降级。

        Args:
            effort: 当前 effort 级别

        Returns:
            EffortLevel: 反向降级后的 effort 级别
        """
        # LOW/MEDIUM/HIGH 不需要降级
        if effort in cls.SUPPORTED_LEVELS:
            return effort
        # XHIGH/MAX 按链式降级
        chain = cls.FALLBACK_CHAIN.get(effort, [])
        return chain[0] if chain else EffortLevel.HIGH
