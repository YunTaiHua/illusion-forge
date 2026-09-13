"""
计划文件管理模块
================

提供计划模式下计划文件的路径管理和 slug 生成功能。
计划文件存储在 ~/.illusion/plans/ 目录下，文件名为可读的 word slug 或 LLM 指定的名称。

主要功能：
    - 生成可读的计划文件 slug（adjective-noun 格式或 LLM 指定名称）
    - 管理计划文件的路径和缓存
    - 读取计划文件内容

函数说明：
    - get_plans_dir: 获取计划文件目录
    - get_plan_slug: 获取或生成会话的计划文件 slug
    - get_plan_file_path: 获取计划文件完整路径
    - get_plan: 读取计划文件内容

使用示例：
    >>> from illusion_forge.config.plan_file import get_plan_file_path, get_plan
    >>> path = get_plan_file_path("session-123")
    >>> content = get_plan("session-123")
"""

from __future__ import annotations

import random
from pathlib import Path

from illusion_forge.config.paths import get_config_dir

# 默认会话标识（当无真实 session_id 时使用）
DEFAULT_SESSION_ID = "session"

# slug 缓存：session_id -> slug
_slug_cache: dict[str, str] = {}

# 内置英文单词列表（adjective-noun 格式）
_ADJECTIVES = [
    "swift", "bright", "calm", "dark", "eager", "fair", "grand", "happy",
    "keen", "light", "mild", "noble", "proud", "quick", "sharp", "tall",
    "vast", "warm", "bold", "cool", "deep", "fine", "gold", "high",
    "just", "kind", "long", "near", "pure", "rich", "safe", "true",
    "wild", "wise", "brave", "clear", "eager", "fierce", "gentle",
    "humble", "lively", "noble", "polite", "rare", "silent", "sturdy",
    "tender", "unique", "vivid", "young", "ancient", "azure", "crimson",
    "divine", "emerald", "frozen", "golden", "hidden", "ivory", "jade",
    "lunar", "mystic", "ocean", "primal", "royal", "solar", "stellar",
    "velvet", "amber", "bronze", "coral", "ebony", "frost", "marble",
    "onyx", "pearl", "ruby", "silver", "topaz", "arctic", "blazing",
    "cosmic", "daring", "ethereal", "forged", "gleaming", "howling",
    "iron", "luminous", "molten", "orbiting", "phantom", "radiant",
    "soaring", "thunder", "wandering", "crystal", "drifting", "falling",
    "glowing", "roaming", "rising", "shining", "floating", "burning",
    "humming", "ringing", "singing", "spinning", "weaving",
]
_NOUNS = [
    "phoenix", "lighthouse", "glacier", "summit", "forest", "meadow",
    "harbor", "temple", "bridge", "garden", "falcon", "panther", "wolf",
    "eagle", "hawk", "dolphin", "tiger", "dragon", "storm", "comet",
    "nebula", "quasar", "pulsar", "aurora", "horizon", "cascade",
    "fortress", "citadel", "bastion", "spire", "tower", "keep", "vault",
    "forge", "anvil", "beacon", "compass", "anchor", "helm", "tide",
    "crest", "peak", "vale", "ridge", "spring", "delta", "shore",
    "canopy", "thicket", "grove", "orchard", "prairie", "tundra",
    "savanna", "reef", "lagoon", "oasis", "canyon", "ravine", "bluff",
    "cliff", "cavern", "grotto", "sanctum", "haven", "refuge", "nexus",
    "core", "pulse", "spark", "ember", "blaze", "flame", "flicker",
    "gleam", "glimmer", "shadow", "mist", "haze", "fog", "breeze",
    "gust", "squall", "tempest", "whirlpool", "maelstrom", "vortex",
    "prism", "spectrum", "echo", "ripple", "wave", "current", "drift",
    "lattice", "matrix", "vector", "tensor", "cipher", "sigil", "rune",
    "glyph", "symbol", "token", "shard", "crystal", "gem", "jewel",
]


def get_plans_dir() -> Path:
    """返回计划文件目录，不存在则创建。

    路径: ~/.illusion/plans/

    Returns:
        Path: 计划文件目录路径
    """
    plans_dir = get_config_dir() / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    return plans_dir


def _generate_slug() -> str:
    """生成可读的 word slug（adjective-noun 格式）。

    Returns:
        str: 如 "swift-phoenix", "cosmic-lighthouse"
    """
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    return f"{adj}-{noun}"


def _sanitize_slug(name: str) -> str:
    """将用户输入的名称规范化为安全的文件名 slug。

    只保留字母、数字、连字符和下划线，去除首尾分隔符。

    Args:
        name: 用户输入的名称

    Returns:
        str: 规范化后的 slug，输入无效时返回空字符串
    """
    sanitized = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "-" for ch in name)
    return sanitized.strip("-_").lower()


def get_plan_slug(session_id: str, *, name: str | None = None) -> str:
    """获取或生成当前会话的计划文件 slug，带缓存。

    如果提供了 name 参数且非空，使用 sanitize 后的 name 作为 slug。
    否则随机生成。首次调用时生成并缓存，后续调用返回缓存值。

    Args:
        session_id: 会话标识
        name: 可选的显式名称（由 LLM 传入）

    Returns:
        str: 计划文件的 slug
    """
    slug = _slug_cache.get(session_id)
    if slug:
        return slug

    # 优先使用显式名称
    if name:
        clean = _sanitize_slug(name)
        if clean:
            _slug_cache[session_id] = clean
            return clean

    # 回退到随机生成（碰撞时追加数字后缀）
    plans_dir = get_plans_dir()
    slug = _generate_slug()
    if (plans_dir / f"{slug}.md").exists():
        for i in range(2, 100):
            candidate = f"{slug}-{i}"
            if not (plans_dir / f"{candidate}.md").exists():
                slug = candidate
                break

    _slug_cache[session_id] = slug
    return slug


def get_plan_file_path(session_id: str, *, name: str | None = None) -> Path:
    """返回计划文件的完整路径。

    路径格式: ~/.illusion/plans/{slug}.md

    Args:
        session_id: 会话标识
        name: 可选的显式名称（由 LLM 传入）

    Returns:
        Path: 计划文件完整路径
    """
    slug = get_plan_slug(session_id, name=name)
    return get_plans_dir() / f"{slug}.md"


def get_plan(session_id: str) -> str | None:
    """读取计划文件内容。

    Args:
        session_id: 会话标识

    Returns:
        str | None: 计划文件内容，不存在返回 None
    """
    path = get_plan_file_path(session_id)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
