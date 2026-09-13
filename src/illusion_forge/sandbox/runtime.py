"""沙箱核心运行时 — 生命周期管理、配置热重载、平台调度

SandboxRuntime 是沙箱系统的核心协调器，负责：
- 初始化和管理平台特定的沙箱实现
- 包装命令为沙箱命令
- 管理违规监控存储
- 处理命令执行后的清理
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .platforms.base import SandboxPlatform, SandboxPlatformConfig
from .violation_store import SandboxViolationStore

logger = logging.getLogger(__name__)


def _detect_platform() -> str:
    """检测当前平台名称"""
    import os
    import sys
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform == "win32":
        return "windows"
    elif sys.platform == "linux":
        # 检测 WSL
        try:
            with open("/proc/version", "r") as f:
                if "microsoft" in f.read().lower():
                    return "wsl"
        except (OSError, PermissionError):
            pass
        if os.environ.get("WSL_DISTRO_NAME"):
            return "wsl"
        return "linux"
    return "unknown"


def _get_platform_impl(platform_name: str) -> SandboxPlatform:
    """获取平台实现实例"""
    if platform_name in ("linux", "wsl"):
        from .platforms.linux import LinuxSandboxPlatform
        return LinuxSandboxPlatform()
    elif platform_name == "macos":
        from .platforms.macos import MacOSSandboxPlatform
        return MacOSSandboxPlatform()
    else:
        raise ValueError(f"不支持的沙箱平台: {platform_name}")


class SandboxRuntime:
    """沙箱核心运行时

    管理沙箱的完整生命周期：初始化、命令包装、清理、重置。
    """

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._platform: SandboxPlatform | None = None
        self._platform_name: str = ""
        self._enabled: bool = False
        self._violation_store = SandboxViolationStore()
        self._ask_callback: Callable[[str], bool] | None = None

    def initialize(
        self,
        config: dict[str, Any],
        ask_callback: Callable[[str], bool] | None = None,
    ) -> None:
        """初始化沙箱运行时

        Args:
            config: 沙箱配置字典
            ask_callback: 网络请求确认回调（未知域名时调用）
        """
        self._config = config
        self._ask_callback = ask_callback

        self._platform_name = _detect_platform()

        # 检查平台是否在启用列表中
        enabled_platforms = config.get("enabled_platforms", [])
        if enabled_platforms and self._platform_name not in enabled_platforms:
            logger.info("沙箱对平台 %s 已禁用（不在 enabled_platforms 中）", self._platform_name)
            self._enabled = False
            return

        # 未知平台与 Windows：自动降级（禁用沙箱），不影响命令执行。
        # Windows 原生不支持 OS 级沙箱（bwrap/sandbox-exec 均为 POSIX 专属），
        # Windows 的隔离依赖权限层（风险分级 + 文件系统白名单）。
        if self._platform_name in ("unknown", "windows"):
            logger.info("沙箱平台 %s 不支持 OS 级沙箱，已禁用", self._platform_name)
            self._enabled = False
            return

        self._platform = _get_platform_impl(self._platform_name)

        # 检查依赖；缺失时自动降级（禁用沙箱），不影响命令执行
        errors = self._platform.check_dependencies()
        if errors:
            logger.warning("沙箱依赖缺失，沙箱已禁用: %s", "; ".join(errors))
            self._platform = None
            self._enabled = False
            return

        self._enabled = True
        logger.info("沙箱运行时已初始化 (平台: %s)", self._platform_name)

    def is_enabled(self) -> bool:
        """沙箱是否已启用并就绪"""
        return self._enabled

    def get_platform_name(self) -> str:
        """获取当前平台名称"""
        return self._platform_name

    def get_violation_store(self) -> SandboxViolationStore:
        """获取违规事件存储"""
        return self._violation_store

    def wrap_command(self, command: list[str], shell: str = "bash") -> list[str]:
        """将命令包装为沙箱命令

        Args:
            command: 原始命令 argv
            shell: shell 名称

        Returns:
            包装后的命令 argv（未启用时返回原命令）
        """
        if not self._enabled or self._platform is None:
            return command

        config = self._build_platform_config()
        return self._platform.wrap_command(command, config)

    def cleanup_after_command(self) -> None:
        """命令执行后清理"""
        if self._platform:
            self._platform.cleanup_after_command()

    def reset(self) -> None:
        """完全重置沙箱状态"""
        self._enabled = False
        self._platform = None
        self._config = {}

    def update_config(self, new_config: dict[str, Any]) -> None:
        """热重载配置

        Args:
            new_config: 新的沙箱配置
        """
        import copy
        self._config = copy.deepcopy(new_config)
        # 沙箱始终开启：热重载时重新初始化，使平台/依赖/排除规则即时生效
        self.initialize(new_config, self._ask_callback)

    def annotate_stderr_with_sandbox_failures(self, command: str, stderr: str) -> str:
        """在 stderr 中追加违规信息

        Args:
            command: 执行的命令
            stderr: 原始 stderr 内容

        Returns:
            追加了违规信息的 stderr
        """
        from .utils import encode_sandboxed_command
        encoded = encode_sandboxed_command(command)
        violations = self._violation_store.get_violations_for_command(encoded)
        if not violations:
            return stderr
        lines = ["\n<sandbox_violations>"]
        for v in violations:
            lines.append(
                f'  <violation command="{v.command}" timestamp="{v.timestamp}">{v.line}</violation>'
            )
        lines.append("</sandbox_violations>")
        return stderr + "\n".join(lines)

    def _build_platform_config(self) -> SandboxPlatformConfig:
        """从运行时配置构建平台配置"""
        fs = self._config.get("filesystem", {})
        net = self._config.get("network", {})

        # 生成代理环境变量（仅在有网络限制时）
        proxy_env: dict[str, str] = {}
        if net.get("allowed_domains") or net.get("denied_domains"):
            from .proxy.env_vars import generate_sandbox_proxy_env
            proxy_env = generate_sandbox_proxy_env(
                http_port=net.get("http_proxy_port") or 0,
                socks_port=net.get("socks_proxy_port") or 0,
                platform_name=self._platform_name,
            )

        return SandboxPlatformConfig(
            allow_write=fs.get("allow_write", ["."]),
            deny_write=fs.get("deny_write", []),
            deny_read=fs.get("deny_read", []),
            allow_read=fs.get("allow_read", []),
            network_enabled=bool(net.get("allowed_domains") or net.get("denied_domains")),
            http_proxy_port=net.get("http_proxy_port"),
            socks_proxy_port=net.get("socks_proxy_port"),
            proxy_env=proxy_env,
            allow_all_unix_sockets=net.get("allow_all_unix_sockets", False),
            enable_weaker_nested_sandbox=self._config.get("enable_weaker_nested_sandbox", False),
            enable_weaker_network_isolation=self._config.get("enable_weaker_network_isolation", False),
        )
