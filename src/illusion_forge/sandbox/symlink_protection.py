"""符号链接攻击防护

防止通过符号链接绕过沙箱文件系统限制。
检测符号链接解析是否指向预期边界之外。
"""
from __future__ import annotations

import os


def is_symlink_outside_boundary(original_path: str, resolved_path: str) -> bool:
    """检测符号链接解析是否指向边界外

    用于防止符号链接替换攻击：攻击者删除合法目录，创建同名符号链接指向敏感位置。

    Args:
        original_path: 原始路径（沙箱允许的路径）
        resolved_path: 符号链接解析后的实际路径

    Returns:
        True 表示解析路径在边界外（危险），False 表示在边界内（安全）
    """
    resolved = resolved_path.rstrip("/")
    original = original_path.rstrip("/")

    # 解析到根目录 → 越界
    if resolved == "/" or resolved == "":
        return True

    # 单组件路径（如 /tmp, /usr）→ 越界
    parts = resolved.strip("/").split("/")
    if len(parts) <= 1:
        return True

    # macOS 合法系统链接: /tmp/* → /private/tmp/*
    if original.startswith("/tmp/") and resolved.startswith("/private/tmp/"):
        return False
    if original.startswith("/var/") and resolved.startswith("/private/var/"):
        return False

    # 解析路径是原始路径的祖先 → 越界
    if resolved.startswith(original + "/") or resolved == original:
        return False

    # 检查 canonical 形式（macOS /private/ 前缀）
    if original.startswith("/private") and not resolved.startswith("/private"):
        canonical = "/private" + original
        if resolved == canonical or resolved.startswith(canonical + "/"):
            return False

    # 如果原始路径以解析路径为前缀，说明解析到了更上层 → 越界
    if original.startswith(resolved + "/"):
        return True

    return True


def normalize_path_for_sandbox(path_pattern: str, cwd: str | None = None) -> str:
    """路径规范化：展开 ~、解析相对路径

    Args:
        path_pattern: 原始路径模式
        cwd: 工作目录（默认使用 os.getcwd()）

    Returns:
        规范化后的绝对路径
    """
    # 展开 ~
    expanded = os.path.expanduser(path_pattern)
    # 解析相对路径
    if not os.path.isabs(expanded):
        if cwd is None:
            cwd = os.getcwd()
        expanded = os.path.join(cwd, expanded)
    # 规范化
    return os.path.normpath(expanded)
