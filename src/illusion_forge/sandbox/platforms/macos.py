"""macOS 平台沙箱实现 — Apple Seatbelt

使用 macOS 内置的 sandbox-exec 和 Seatbelt 框架实现沙箱隔离。
Seatbelt 使用 S-expression 格式的配置文件，默认拒绝所有操作。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from .base import SandboxPlatform, SandboxPlatformConfig


class MacOSSandboxPlatform(SandboxPlatform):
    """macOS Seatbelt 沙箱平台"""

    def check_dependencies(self) -> list[str]:
        """检查 sandbox-exec 是否可用"""
        errors = []
        if not shutil.which("sandbox-exec"):
            errors.append("缺少 sandbox-exec（macOS 内置）")
        return errors

    def wrap_command(self, command: list[str], config: SandboxPlatformConfig) -> list[str]:
        """生成 Seatbelt profile 并包装命令"""
        import shlex

        log_tag = f"illusion_sandbox_{os.getpid()}"
        profile = self._generate_seatbelt_profile(config, log_tag)

        # 写入临时 profile 文件
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="illusion-seatbelt-", suffix=".sb", delete=False
        ) as profile_file:
            profile_file.write(profile)

        shell = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
        cmd_str = shlex.join(command)

        # 构建代理环境变量前缀
        env_prefix = ""
        for key, value in config.proxy_env.items():
            env_prefix += f"{key}={shlex.quote(value)} "

        # sandbox-exec -p <profile> <shell> -c <command>
        wrapped = (
            f"{env_prefix}sandbox-exec -p {shlex.quote(profile_file.name)} "
            f"{shell} -c {shlex.quote(cmd_str)}"
        )
        return ["sh", "-c", wrapped]

    def cleanup_after_command(self) -> None:
        """Seatbelt 自动清理，无需额外操作"""

    def _generate_seatbelt_profile(
        self, config: SandboxPlatformConfig, log_tag: str
    ) -> str:
        """生成 Seatbelt 沙箱配置文件

        Seatbelt profile 使用 S-expression 格式，默认拒绝所有操作，
        然后通过 allow 规则选择性放行。
        """
        lines = [
            "(version 1)",
            f'(deny default (with message "{log_tag}"))',
            "",
            "; 进程权限",
            "(allow process-exec process-fork)",
            "(allow process-info* signal)",
            "",
            "; Mach IPC (系统服务)",
            '(allow mach-lookup (global-name "com.apple.logd"))',
            '(allow mach-lookup (global-name "com.apple.system.notification_center"))',
            '(allow mach-lookup (global-name "com.apple.system.opendirectoryd.libinfo"))',
            '(allow mach-lookup (global-name "com.apple.system.opendirectoryd.membership"))',
            "",
        ]

        # 文件读取规则
        if config.deny_read:
            lines.append("; 文件读取 — 默认允许，拒绝特定路径")
            lines.append("(allow file-read*)")
            for path in config.deny_read:
                lines.append(f'(deny file-read* (subpath "{self._escape_path(path)}"))')
            lines.append("")
        else:
            lines.append("(allow file-read*)")
            lines.append("")

        # 文件写入规则
        lines.append("; 文件写入 — 默认拒绝，允许特定路径")
        for path in config.allow_write:
            resolved = os.path.expanduser(path)
            if not os.path.isabs(resolved):
                resolved = os.path.join(os.getcwd(), resolved)
            lines.append(f'(allow file-write* (subpath "{self._escape_path(resolved)}"))')
        for path in config.deny_write:
            lines.append(f'(deny file-write* (subpath "{self._escape_path(path)}"))')
        lines.append("")

        # 网络规则
        if config.network_enabled and config.http_proxy_port:
            lines.append("; 网络 — 仅允许连接代理")
            lines.append("(deny network*)")
            lines.append(
                f'(allow network* (local tcp "localhost:{config.http_proxy_port}"))'
            )
            if config.socks_proxy_port:
                lines.append(
                    f'(allow network* (local tcp "localhost:{config.socks_proxy_port}"))'
                )
            # enable_weaker_network_isolation：允许访问 trustd（Go 工具 TLS 校验所需，
            # 降低网络隔离，存在数据外泄风险）
            if config.enable_weaker_network_isolation:
                lines.append(
                    '(allow network* (remote unix-socket "/private/var/run/com.apple.trustd.agent"))'
                )
        else:
            lines.append("(allow network*)")
        lines.append("")

        # 系统权限
        lines.append("; 系统")
        lines.append("(allow iokit-get-properties)")
        lines.append("(allow sysctl-read)")

        return "\n".join(lines) + "\n"

    @staticmethod
    def _escape_path(path: str) -> str:
        """转义路径中的特殊字符用于 Seatbelt profile"""
        return json.dumps(path)[1:-1]
