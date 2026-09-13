"""
Token 估算工具
==============

本模块提供 Token 估算功能，使用改进的启发式方法：
- 基础估算：字符数 / 4（适用于英文为主的文本）
- CJK 优化：中日韩文字按 2 字符/token 估算（更密集）
- JSON 优化：JSON 内容按 2 字节/token 估算
- 混合文本自动检测

主要功能：
    - 估算单个文本的 Token 数量
    - 估算消息列表的总 Token 数量
    - 检测文本是否包含 CJK 字符

使用示例：
    >>> from illusion_forge.services.token_estimation import estimate_tokens
    >>> tokens = estimate_tokens("Hello, world!")
    >>> print(tokens)  # 输出约 4
    >>> tokens = estimate_tokens("你好世界")
    >>> print(tokens)  # 输出约 4
"""

from __future__ import annotations

import re

# CJK 字符范围的正则表达式（匹配中日韩统一表意文字等）
_CJK_PATTERN = re.compile(
    r"[\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\u3400-\u4dbf"  # CJK Unified Ideographs Extension A
    r"\uf900-\ufaff"  # CJK Compatibility Ideographs
    r"\u3040-\u309f"  # Hiragana
    r"\u30a0-\u30ff"  # Katakana
    r"\uac00-\ud7af"  # Hangul Syllables
    r"]"
)


def _has_cjk(text: str) -> bool:
    """检查文本是否包含 CJK 字符。"""
    return bool(_CJK_PATTERN.search(text))


def estimate_tokens(text: str) -> int:
    """使用改进的启发式方法估算纯文本的 Token 数。

    对于英文为主的文本，使用字符数 / 4 的估算。
    对于包含 CJK 字符的文本，使用字符数 / 2 的估算（CJK 文字更密集）。
    """
    if not text:
        return 0
    if _has_cjk(text):
        # CJK 文字：每个字符约 0.5-1 token，使用 /2 估算
        return max(1, (len(text) + 1) // 2)
    # 英文为主：约 4 字符/token
    return max(1, (len(text) + 3) // 4)


def estimate_tokens_for_json(text: str) -> int:
    """估算 JSON 文本的 Token 数。

    JSON 内容比普通文本更密集，使用 2 字节/token 估算。
    """
    if not text:
        return 0
    return max(1, len(text.encode("utf-8")) // 2)


def estimate_message_tokens(messages: list[str]) -> int:
    """估算消息字符串集合的 Token 总数。"""
    return sum(estimate_tokens(message) for message in messages)
