"""
文件状态缓存
============

本模块提供文件状态的 LRU 缓存，用于跟踪已读取文件的内容和修改时间。

主要组件：
    - FileState: 文件状态快照数据类
    - FileStateCache: 文件状态 LRU 缓存

设计提供：
    - Read 去重：相同文件+范围+mtime 返回存根而非重新读取
    - mtime 过期检测：文件被外部修改后自动失效
    - Edit/Write 后更新缓存：后续编辑不需要重新读取

使用示例：
    >>> from illusion_forge.utils.file_state_cache import FileStateCache, FileState
    >>> cache = FileStateCache()
    >>> cache.set("/path/to/file.py", FileState(content="...", timestamp=1234567890.0))
    >>> state = cache.get("/path/to/file.py")
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileState:
    """文件状态快照。

    存储文件的内容、修改时间和读取参数，用于缓存验证和去重。

    Attributes:
        content: 文件内容
        timestamp: 文件修改时间 (mtime)
        offset: Read 工具的行偏移（None 表示来自 Edit/Write）
        limit: Read 工具的行数限制（None 表示完整读取或来自 Edit/Write）
        is_partial_view: 是否为部分视图（内容与磁盘不一致）
    """

    content: str
    timestamp: float
    offset: int | None = None
    limit: int | None = None
    is_partial_view: bool = False


# 默认最大缓存条目数
DEFAULT_MAX_ENTRIES: int = 100

# 默认最大缓存大小（25MB）
DEFAULT_MAX_SIZE_BYTES: int = 25 * 1024 * 1024


class FileStateCache:
    """文件状态 LRU 缓存。

    使用字典实现简单的 LRU 缓存，限制条目数和总字节数。
    路径标准化确保 Windows/Unix 路径一致性。

    Attributes:
        _max_entries: 最大条目数
        _max_size_bytes: 最大字节数
        _cache: 缓存字典
        _access_order: LRU 访问顺序
        _current_size: 当前缓存大小（字节）

    使用示例：
        >>> cache = FileStateCache(max_entries=50)
        >>> cache.set("/path/to/file.py", FileState(content="...", timestamp=1234567890.0))
        >>> if cache.has("/path/to/file.py"):
        ...     state = cache.get("/path/to/file.py")
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
    ) -> None:
        """初始化缓存。

        Args:
            max_entries: 最大条目数
            max_size_bytes: 最大字节数
        """
        self._max_entries = max_entries
        self._max_size_bytes = max_size_bytes
        self._cache: dict[str, FileState] = {}
        self._access_order: list[str] = []  # LRU 顺序，末尾为最近使用
        self._current_size: int = 0  # 当前缓存大小（字节）

    def get(self, key: str) -> FileState | None:
        """获取缓存条目，更新访问顺序。

        Args:
            key: 文件路径

        Returns:
            FileState 或 None（如果不存在）
        """
        normalized = self._normalize(key)
        if normalized in self._cache:
            # 移到末尾（最近使用）
            self._access_order.remove(normalized)
            self._access_order.append(normalized)
            return self._cache[normalized]
        return None

    def set(self, key: str, value: FileState) -> None:
        """设置缓存条目，必要时驱逐旧条目。

        Args:
            key: 文件路径
            value: 文件状态
        """
        normalized = self._normalize(key)
        entry_size = self._calculate_size(value)

        # 如果已存在，先移除旧条目
        if normalized in self._cache:
            old_value = self._cache[normalized]
            self._current_size -= self._calculate_size(old_value)
            self._access_order.remove(normalized)

        # 驱逐条目直到有足够空间
        while (
            len(self._cache) >= self._max_entries
            or self._current_size + entry_size > self._max_size_bytes
        ):
            if not self._access_order:
                break
            self._evict_lru()

        self._cache[normalized] = value
        self._access_order.append(normalized)
        self._current_size += entry_size

    def has(self, key: str) -> bool:
        """检查缓存是否包含指定键。

        Args:
            key: 文件路径

        Returns:
            是否存在
        """
        return self._normalize(key) in self._cache

    def delete(self, key: str) -> bool:
        """删除指定条目。

        Args:
            key: 文件路径

        Returns:
            是否成功删除
        """
        normalized = self._normalize(key)
        if normalized in self._cache:
            old_value = self._cache[normalized]
            self._current_size -= self._calculate_size(old_value)
            del self._cache[normalized]
            self._access_order.remove(normalized)
            return True
        return False

    def clear(self) -> None:
        """清空缓存。"""
        self._cache.clear()
        self._access_order.clear()
        self._current_size = 0

    @property
    def size(self) -> int:
        """当前条目数。"""
        return len(self._cache)

    @property
    def max(self) -> int:
        """最大条目数。"""
        return self._max_entries

    @property
    def max_size(self) -> int:
        """最大字节数。"""
        return self._max_size_bytes

    @property
    def calculated_size(self) -> int:
        """当前缓存大小（字节）。"""
        return self._current_size

    def keys(self) -> Generator[str, None, None]:
        """返回所有键。"""
        yield from self._cache.keys()

    def entries(self) -> Generator[tuple[str, FileState], None, None]:
        """返回所有键值对，按访问顺序排列。"""
        for key in self._access_order:
            yield key, self._cache[key]

    def _normalize(self, key: str) -> str:
        """标准化路径，确保 Windows/Unix 一致性。

        Args:
            key: 原始路径

        Returns:
            标准化后的路径
        """
        return str(Path(key).resolve())

    def _calculate_size(self, value: FileState) -> int:
        """计算条目大小（字节）。

        Args:
            value: 文件状态

        Returns:
            字节大小
        """
        return max(1, len(value.content.encode("utf-8")))

    def _evict_lru(self) -> None:
        """驱逐最久未使用的条目。"""
        if self._access_order:
            oldest = self._access_order.pop(0)
            old_value = self._cache.pop(oldest)
            self._current_size -= self._calculate_size(old_value)


def create_file_state_cache(
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
) -> FileStateCache:
    """工厂函数，创建文件状态缓存。

    Args:
        max_entries: 最大条目数
        max_size_bytes: 最大字节数

    Returns:
        FileStateCache 实例
    """
    return FileStateCache(max_entries, max_size_bytes)


def clone_file_state_cache(cache: FileStateCache) -> FileStateCache:
    """克隆文件状态缓存。

    保留大小限制配置，复制所有条目。

    Args:
        cache: 源缓存

    Returns:
        克隆的缓存
    """
    cloned = FileStateCache(cache.max, cache.max_size)
    for key, value in cache.entries():
        cloned.set(key, value)
    return cloned


def merge_file_state_caches(
    first: FileStateCache,
    second: FileStateCache,
) -> FileStateCache:
    """合并两个文件状态缓存。

    以 timestamp 较新者为准。

    Args:
        first: 第一个缓存
        second: 第二个缓存（优先级更高）

    Returns:
        合并后的缓存
    """
    merged = clone_file_state_cache(first)
    for file_path, file_state in second.entries():
        existing = merged.get(file_path)
        # 只有当新条目更新时才覆盖
        if existing is None or file_state.timestamp > existing.timestamp:
            merged.set(file_path, file_state)
    return merged
