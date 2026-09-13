"""
会话压缩模块数据模型。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AutoCompactState:
    """跨查询循环轮次持久的可变状态。"""

    compacted: bool = False
    turn_counter: int = 0
    consecutive_failures: int = 0
    last_compacted_at_turn: int = 0
    warning_suppressed: bool = False


@dataclass
class TokenWarningState:
    """上下文使用量的警告状态。"""

    is_above_warning_threshold: bool = False
    is_above_autocompact_threshold: bool = False
    is_at_blocking_limit: bool = False
    estimated_tokens: int = 0
    threshold: int = 0
    context_window: int = 0
