"""沙箱工具函数 — glob 展开、路径规范化、命令编码、代理环境变量

提供沙箱系统共用的工具函数。
"""
from __future__ import annotations

import base64
import os


def encode_sandboxed_command(command: str) -> str:
    """截断到 100 字符并 base64 编码

    用于违规监控中匹配命令。
    """
    truncated = command[:100]
    return base64.b64encode(truncated.encode("utf-8")).decode("ascii")


def decode_sandboxed_command(encoded: str) -> str:
    """解码 base64 编码的命令"""
    return base64.b64decode(encoded).decode("utf-8")


def contains_glob_chars(path_pattern: str) -> bool:
    """检查路径是否包含 glob 字符（*, ?, [, ]）"""
    return any(c in path_pattern for c in "*?[]")


def remove_trailing_glob_suffix(path_pattern: str) -> str:
    """移除尾部的 /** glob 后缀"""
    if path_pattern.endswith("/**"):
        return path_pattern[:-3]
    return path_pattern


def normalize_case_for_comparison(path_str: str) -> str:
    """小写化路径用于大小写不敏感比较（macOS/Windows）"""
    return path_str.lower()


def get_default_write_paths() -> list[str]:
    """获取默认可写路径列表

    这些路径在沙箱中始终允许写入，无论用户如何配置。
    """
    paths = [
        "/dev/stdout",
        "/dev/stderr",
        "/dev/null",
        "/dev/tty",
        "/tmp/illusion",
    ]
    # 添加用户特定路径（如果存在）
    npm_logs = os.path.expanduser("~/.npm/_logs")
    if os.path.exists(os.path.dirname(npm_logs)):
        paths.append(npm_logs)
    from illusion_forge.config.paths import get_logs_dir

    paths.append(str(get_logs_dir() / "debug"))
    return paths


def generate_proxy_env_vars(http_port: int, socks_port: int) -> dict[str, str]:
    """生成代理环境变量

    Args:
        http_port: HTTP 代理端口
        socks_port: SOCKS5 代理端口

    Returns:
        环境变量字典
    """
    no_proxy = (
        "localhost,127.0.0.1,*.local,"
        "169.254.*,10.*,"
        "172.16.*,172.17.*,172.18.*,172.19.*,"
        "172.20.*,172.21.*,172.22.*,172.23.*,"
        "172.24.*,172.25.*,172.26.*,172.27.*,"
        "172.28.*,172.29.*,172.30.*,172.31.*,"
        "192.168.*"
    )
    return {
        "SANDBOX_RUNTIME": "1",
        "HTTP_PROXY": f"http://127.0.0.1:{http_port}",
        "HTTPS_PROXY": f"http://127.0.0.1:{http_port}",
        "http_proxy": f"http://127.0.0.1:{http_port}",
        "https_proxy": f"http://127.0.0.1:{http_port}",
        "ALL_PROXY": f"socks5h://127.0.0.1:{socks_port}",
        "all_proxy": f"socks5h://127.0.0.1:{socks_port}",
        "NO_PROXY": no_proxy,
        "no_proxy": no_proxy,
    }
