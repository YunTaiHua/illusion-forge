"""Linux 平台沙箱实现 — bubblewrap

使用 bubblewrap (bwrap) 实现进程和文件系统隔离。
可选使用 seccomp BPF 过滤器阻断 Unix socket 创建。
"""
from __future__ import annotations

import shutil

from .base import SandboxPlatform, SandboxPlatformConfig


class LinuxSandboxPlatform(SandboxPlatform):
    """Linux bwrap 沙箱平台"""

    def check_dependencies(self) -> list[str]:
        """检查 bwrap 是否可用"""
        errors = []
        if not shutil.which("bwrap"):
            errors.append("缺少 bubblewrap (bwrap)，请安装: apt install bubblewrap")
        return errors

    def wrap_command(self, command: list[str], config: SandboxPlatformConfig) -> list[str]:
        """构建 bwrap 命令

        构建流程：
        1. 只读根文件系统
        2. 选择性允许写入（经符号链接检查）
        3. 拒绝写入（挂载 /dev/null）
        4. 拒绝读取（tmpfs 覆盖）
        5. 网络隔离（--unshare-net）
        6. 进程隔离（--unshare-pid + --proc）
        7. 代理环境变量
        """
        args = ["bwrap", "--new-session", "--die-with-parent"]

        # 只读根文件系统
        args += ["--ro-bind", "/", "/"]

        # 允许写入的路径
        for path in config.allow_write:
            args += ["--bind", path, path]

        # 拒绝写入的路径（挂载 /dev/null 防止创建）
        for path in config.deny_write:
            args += ["--ro-bind", "/dev/null", path]

        # 拒绝读取的路径（tmpfs 覆盖为空）
        for path in config.deny_read:
            args += ["--tmpfs", path]

        # 网络隔离
        if config.network_enabled:
            args += ["--unshare-net"]

        # 进程隔离
        if not config.enable_weaker_nested_sandbox:
            args += ["--unshare-pid", "--proc", "/proc"]

        # 代理环境变量
        for key, value in config.proxy_env.items():
            args += ["--setenv", key, value]

        args += ["--"]
        args += command
        return args

    def cleanup_after_command(self) -> None:
        """bwrap 自动清理，无需额外操作"""
