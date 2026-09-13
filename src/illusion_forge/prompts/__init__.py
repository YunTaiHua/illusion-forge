"""
提示词模块
==========

本模块提供 IllusionForge 系统提示词构建功能。

主要组件：
    - build_system_prompt: 构建系统提示词
    - build_runtime_system_prompt: 构建运行时系统提示词
    - discover_claude_md_files: 发现 Claude.md 文件
    - load_claude_md_prompt: 加载 Claude.md 提示词
    - get_environment_info: 获取环境信息

使用示例：
    >>> from illusion_forge.prompts import build_system_prompt, get_environment_info
"""

from illusion_forge.prompts.channel_hints import get_channel_hint
from illusion_forge.prompts.claudemd import discover_claude_md_files, load_claude_md_prompt
from illusion_forge.prompts.context import build_runtime_system_prompt
from illusion_forge.prompts.environment import get_environment_info
from illusion_forge.prompts.system_prompt import build_system_prompt

__all__ = [
    "build_runtime_system_prompt",
    "build_system_prompt",
    "discover_claude_md_files",
    "get_channel_hint",
    "get_environment_info",
    "load_claude_md_prompt",
]
