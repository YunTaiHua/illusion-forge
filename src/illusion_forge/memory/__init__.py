"""
记忆模块
========

本模块提供 IllusionForge 记忆/上下文管理功能。

主要组件：
    - add_memory_entry: 添加记忆条目
    - find_relevant_memories: 查找相关记忆
    - get_memory_entrypoint: 获取记忆入口点（MEMORY.md）
    - get_memory_dir: 获取全局 memory 根目录
    - get_memory_dir_for_cwd: 获取当前项目使用的记忆目录（自定义优先）
    - get_project_memory_dir: 获取项目默认记忆目录（user 级）
    - list_memory_files: 列出记忆文件
    - load_memory_prompt: 加载记忆提示词
    - remove_memory_entry: 移除记忆条目
    - scan_memory_files: 扫描记忆文件

使用示例：
    >>> from illusion_forge.memory import add_memory_entry, find_relevant_memories
"""

from illusion_forge.memory.manager import add_memory_entry, list_memory_files, remove_memory_entry
from illusion_forge.memory.memdir import load_memory_prompt
from illusion_forge.memory.paths import (
    get_memory_dir,
    get_memory_dir_for_cwd,
    get_memory_entrypoint,
    get_project_memory_dir,
    resolve_custom_memory_dir,
)
from illusion_forge.memory.scan import scan_memory_files
from illusion_forge.memory.search import find_relevant_memories

__all__ = [
    "add_memory_entry",
    "find_relevant_memories",
    "get_memory_dir",
    "get_memory_dir_for_cwd",
    "get_memory_entrypoint",
    "get_project_memory_dir",
    "list_memory_files",
    "load_memory_prompt",
    "remove_memory_entry",
    "resolve_custom_memory_dir",
    "scan_memory_files",
]
