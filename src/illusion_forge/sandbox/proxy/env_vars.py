"""代理环境变量生成

为沙箱内进程生成代理相关的环境变量，使所有网络流量
通过沙箱代理服务器进行域名过滤。
"""
from __future__ import annotations

import os


def generate_sandbox_proxy_env(
    http_port: int,
    socks_port: int,
    platform_name: str,
) -> dict[str, str]:
    """生成沙箱代理环境变量

    Args:
        http_port: HTTP 代理端口
        socks_port: SOCKS5 代理端口
        platform_name: 平台名称（linux/macos/windows/wsl）

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

    env: dict[str, str] = {
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

    # 平台特定的 GIT_SSH_COMMAND
    if platform_name in ("linux", "wsl"):
        env["GIT_SSH_COMMAND"] = f"socat - PROXY:127.0.0.1:%h:%p,proxyport={socks_port}"
    elif platform_name == "macos":
        env["GIT_SSH_COMMAND"] = f"nc -X 5 -x 127.0.0.1:{socks_port} %h %p"

    # 设置 TMPDIR
    tmpdir = os.environ.get("TMPDIR", "/tmp")
    env["TMPDIR"] = tmpdir

    return env
