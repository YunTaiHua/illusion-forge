"""简单的使用量聚合。

本模块提供成本跟踪功能，用于累积会话期间的使用量统计。

主要类：
    - CostTracker: 使用量累积器

使用示例：
    >>> from illusion_forge.engine.cost_tracker import CostTracker
    >>> tracker = CostTracker()
    >>> tracker.add(usage_snapshot)
    >>> print(tracker.total)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from illusion_forge.api.usage import UsageSnapshot

if TYPE_CHECKING:
    from illusion_forge.services.checkpoint_store import RestoreResult


class CostTracker:
    """在整个会话期间累积使用量。

    用于跟踪对话过程中的令牌使用情况，包括输入和输出令牌数。

    Attributes:
        total: 累积的总使用量（只读属性）

    使用示例：
        >>> tracker = CostTracker()
        >>> tracker.add(UsageSnapshot(input_tokens=100, output_tokens=50))
        >>> print(tracker.total.input_tokens)  # 100
    """

    def __init__(self) -> None:
        self._usage = UsageSnapshot()  # 初始化使用量快照

    def add(self, usage: UsageSnapshot) -> None:
        """将使用量快照添加到运行总和。

        Args:
            usage: 要添加的使用量快照
        """
        self._usage = UsageSnapshot(
            input_tokens=self._usage.input_tokens + usage.input_tokens,
            output_tokens=self._usage.output_tokens + usage.output_tokens,
            cache_read_input_tokens=(
                self._usage.cache_read_input_tokens
                + usage.cache_read_input_tokens
            ),
            cache_creation_input_tokens=(
                self._usage.cache_creation_input_tokens
                + usage.cache_creation_input_tokens
            ),
        )

    def set_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        """直接设置累积值（用于 rewind 后恢复）。

        Args:
            input_tokens: 累积 input tokens
            output_tokens: 累积 output tokens
            cache_read_input_tokens: 累积缓存命中 tokens
            cache_creation_input_tokens: 累积缓存写入 tokens
        """
        self._usage = UsageSnapshot(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
        )

    def apply_restore(self, result: RestoreResult) -> None:
        """从 CheckpointStore.restore() 结果恢复累积值。

        Args:
            result: restore 结果
        """
        self._usage = UsageSnapshot(
            input_tokens=result.usage_input,
            output_tokens=result.usage_output,
            cache_read_input_tokens=result.usage_cache_read,
            cache_creation_input_tokens=result.usage_cache_creation,
        )

    @property
    def total(self) -> UsageSnapshot:
        """返回聚合后的使用量。

        Returns:
            UsageSnapshot: 累积的使用量快照
        """
        return self._usage
