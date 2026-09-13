"""
配置系统模块
============

本模块提供 IllusionForge 的配置管理、路径解析和 API 密钥处理功能。

主要组件：
    - Settings: 应用设置
    - EnvConfig: 环境配置
    - load_settings/save_settings: 设置加载/保存
    - get_config_dir/get_data_dir/get_logs_dir: 目录路径获取

使用示例：
    >>> from illusion_forge.config import load_settings, get_config_dir
    >>> settings = load_settings()
    >>> config_path = get_config_dir()
"""

from illusion_forge.config.paths import (
    get_config_dir,
    get_config_file_path,
    get_data_dir,
    get_logs_dir,
)
from illusion_forge.config.settings import (
    Settings,
    load_settings,
    save_settings,
)

__all__ = [
    "Settings",
    "get_config_dir",
    "get_config_file_path",
    "get_data_dir",
    "get_logs_dir",
    "load_settings",
    "save_settings",
]
