"""
工作目录管理模块
================

提供工作目录的校验、规范化、应用与首次登录提示功能。

主要函数：
    - validate_and_normalize: 校验并规范化工作目录路径
    - is_first_login: 判断是否为首次登录
    - prompt_working_directory: 首次登录时提示用户设置工作目录
"""
from __future__ import annotations

from pathlib import Path

from illusion_forge.config.i18n import t as _t
from illusion_forge.config.settings import Settings


def validate_and_normalize(path_str: str) -> tuple[Path | None, str]:
    """校验并规范化工作目录路径

    空字符串视为未设置；合法路径自动新建缺失目录。
    检查 Windows 非法字符（跨平台一致性）：< > : " / \\ | ? *

    Args:
        path_str: 用户输入的路径字符串

    Returns:
        tuple[Path | None, str]: (规范化路径或 None, 错误信息)
        - 空字符串返回 (None, "")
        - 校验成功返回 (resolved_path, "")
        - 校验失败返回 (None, error_msg)
    """
    if not path_str or not path_str.strip():
        return None, ""

    # 检查 Windows 非法字符（跨平台一致性）
    # 即使在 Linux 上也拒绝这些字符，确保行为一致
    # 注意：排除盘符冒号（如 C:），只检查路径部分
    import re
    _path_part = path_str[2:] if len(path_str) > 2 and path_str[1] == ":" else path_str
    if re.search(r'[<>:"|?*]', _path_part):
        return None, _t("set_invalid_path", path=path_str)

    try:
        resolved = Path(path_str).expanduser().resolve()
    except (OSError, ValueError) as exc:
        return None, str(exc)

    # 检查父目录是否存在且可写（避免新建无法创建的路径）
    parent = resolved.parent
    try:
        if not parent.exists():
            return None, _t("set_invalid_path", path=path_str)
    except OSError as exc:
        return None, str(exc)

    # 目录不存在则新建
    if not resolved.exists():
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return None, str(exc)

    return resolved, ""


def is_first_login(settings: Settings) -> bool:
    """判断是否为首次登录：无 env 且无 working_directory

    Args:
        settings: 当前 Settings 实例

    Returns:
        bool: True 表示首次登录
    """
    return not settings.list_envs() and settings.working_directory is None


def prompt_working_directory(settings: Settings) -> None:
    """首次登录时提示用户设置工作目录

    用户回车跳过则不设置；输入合法路径则保存；失败不阻塞。

    Args:
        settings: 当前 Settings 实例（将被修改并保存）
    """
    from illusion_forge.config.settings import save_settings

    raw = input(_t("working_dir_prompt")).strip()
    if not raw:
        print(_t("working_dir_skipped"))
        return

    resolved, err = validate_and_normalize(raw)
    if resolved is None and err:
        print(_t("working_dir_set_failed", error=err))
        return
    if resolved is None:
        print(_t("working_dir_skipped"))
        return

    settings.working_directory = str(resolved)
    try:
        save_settings(settings)
        print(_t("set_saved", path=str(resolved)))
    except OSError as exc:
        print(_t("working_dir_set_failed", error=str(exc)))
