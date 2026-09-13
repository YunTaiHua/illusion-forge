"""
插件变量替换
============

替换钩子命令和技能内容中的插件变量。
"""

from __future__ import annotations

import re
from pathlib import Path


def substitute_plugin_variables(
    template: str,
    plugin_root: Path,
    plugin_data: Path,
) -> str:
    """替换 ${CLAUDE_PLUGIN_ROOT} 和 ${CLAUDE_PLUGIN_DATA}。

    路径统一使用正斜杠，避免 Windows 反斜杠在 bash 中被当作转义符。
    """
    root_str = str(plugin_root).replace("\\", "/")
    data_str = str(plugin_data).replace("\\", "/")
    result = template.replace("${CLAUDE_PLUGIN_ROOT}", root_str)
    result = result.replace("${CLAUDE_PLUGIN_DATA}", data_str)
    return result


def substitute_user_config_variables(
    template: str,
    user_config: dict[str, str],
) -> str:
    """替换 ${user_config.KEY} 变量。

    缺少的 key 会抛出 KeyError。
    """
    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in user_config:
            raise KeyError(f"Missing user_config variable: {key}")
        return user_config[key]

    return re.sub(r'\$\{user_config\.(\w+)\}', replacer, template)
