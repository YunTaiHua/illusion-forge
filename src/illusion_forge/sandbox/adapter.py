"""沙箱运行时适配器模块

本模块实现沙箱管理器（SandboxManager），提供沙箱执行功能。

主要功能：
    - SandboxManager: 沙箱管理器单例
    - SandboxAvailability: 沙箱可用性状态
    - SandboxUnavailableError: 沙箱不可用异常
    - 排除命令匹配
    - 配置热重载

使用示例：
    >>> from illusion_forge.sandbox import SandboxManager
    >>> manager = SandboxManager()
    >>> manager.initialize(settings)
    >>> if manager.should_use_sandbox("rm -rf /tmp/test"):
    ...     wrapped = manager.wrap_command(["bash", "-lc", "rm -rf /tmp/test"])
"""

from __future__ import annotations

import fnmatch
import logging
import re
from collections.abc import Callable
from typing import Any, Self

from .runtime import SandboxRuntime
from .violation_store import SandboxViolationStore

logger = logging.getLogger(__name__)


class SandboxUnavailableError(RuntimeError):
    """当需要沙箱执行但不可用时抛出"""


class SandboxAvailability:
    """当前环境的沙箱运行时可用性状态

    沙箱永远开启（无 enabled 开关），此处仅反映运行时是否就绪。
    """

    def __init__(
        self,
        available: bool,
        reason: str | None = None,
    ) -> None:
        self.available = available
        self.reason = reason

    @property
    def active(self) -> bool:
        """返回是否应该对子进程应用沙箱"""
        return self.available


class SandboxManager:
    """沙箱管理器单例

    管理沙箱的完整生命周期：初始化、可用性检查、命令包装、排除命令匹配。
    """

    _instance: SandboxManager | None = None
    _runtime: SandboxRuntime
    _initialized: bool

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._runtime = SandboxRuntime()
            cls._instance._initialized = False
        return cls._instance  # type: ignore[return-value]

    def initialize(
        self,
        settings: Any,
        ask_callback: Callable[[str], bool] | None = None,
    ) -> None:
        """初始化沙箱管理器

        Args:
            settings: Settings 对象
            ask_callback: 网络请求确认回调
        """
        sandbox_settings = settings.sandbox
        config = self._settings_to_config(sandbox_settings)
        self._runtime.initialize(config, ask_callback)
        self._initialized = True

    def get_availability(self, settings: Any = None) -> SandboxAvailability:
        """获取沙箱可用性

        Args:
            settings: Settings 对象（可选，默认从配置加载）

        Returns:
            SandboxAvailability 对象
        """
        if settings is None:
            from ..config import load_settings
            settings = load_settings()

        if not self._runtime.is_enabled():
            return SandboxAvailability(available=False, reason="沙箱运行时未就绪")

        return SandboxAvailability(available=True)

    def should_use_sandbox(
        self,
        command: str,
        *,
        settings: Any = None,
    ) -> bool:
        """判断命令是否应该使用沙箱

        Args:
            command: 命令字符串
            settings: Settings 对象（可选）

        Returns:
            True 表示应使用沙箱
        """
        if settings is None:
            from ..config import load_settings
            settings = load_settings()

        sandbox_settings = settings.sandbox
        if not self._runtime.is_enabled():
            return False

        if not command:
            return False

        return not self._is_excluded_command(command, sandbox_settings.excluded_commands)

    def wrap_command(self, command: list[str], shell: str = "bash") -> list[str]:
        """包装命令为沙箱命令

        Args:
            command: 原始命令 argv
            shell: shell 名称

        Returns:
            包装后的命令 argv
        """
        return self._runtime.wrap_command(command, shell)

    def cleanup_after_command(self) -> None:
        """命令执行后清理"""
        self._runtime.cleanup_after_command()

    def reset(self) -> None:
        """重置沙箱管理器"""
        self._runtime.reset()
        self._initialized = False

    def update_config(self, settings: Any) -> None:
        """热重载配置

        Args:
            settings: 新的 Settings 对象
        """
        sandbox_settings = settings.sandbox
        config = self._settings_to_config(sandbox_settings)
        self._runtime.update_config(config)

    def get_violation_store(self) -> SandboxViolationStore:
        """获取违规事件存储"""
        return self._runtime.get_violation_store()

    def annotate_stderr_with_sandbox_failures(self, command: str, stderr: str) -> str:
        """在 stderr 中追加违规信息"""
        return self._runtime.annotate_stderr_with_sandbox_failures(command, stderr)

    def _settings_to_config(self, sandbox_settings: Any) -> dict[str, Any]:
        """将 SandboxSettings 转换为运行时配置字典"""
        return {
            "enabled_platforms": sandbox_settings.enabled_platforms,
            "excluded_commands": sandbox_settings.excluded_commands,
            "ignore_violations": sandbox_settings.ignore_violations,
            "enable_weaker_nested_sandbox": sandbox_settings.enable_weaker_nested_sandbox,
            "enable_weaker_network_isolation": sandbox_settings.enable_weaker_network_isolation,
            "mandatory_deny_search_depth": sandbox_settings.mandatory_deny_search_depth,
            "allow_git_config": sandbox_settings.allow_git_config,
            "ripgrep": (
                sandbox_settings.ripgrep.model_dump()
                if sandbox_settings.ripgrep is not None
                else None
            ),
            "filesystem": {
                "allow_write": sandbox_settings.filesystem.allow_write,
                "deny_write": sandbox_settings.filesystem.deny_write,
                "deny_read": sandbox_settings.filesystem.deny_read,
                "allow_read": sandbox_settings.filesystem.allow_read,
            },
            "network": {
                "allowed_domains": sandbox_settings.network.allowed_domains,
                "denied_domains": sandbox_settings.network.denied_domains,
                "allow_unix_sockets": sandbox_settings.network.allow_unix_sockets,
                "allow_all_unix_sockets": sandbox_settings.network.allow_all_unix_sockets,
                "allow_local_binding": sandbox_settings.network.allow_local_binding,
                "http_proxy_port": sandbox_settings.network.http_proxy_port,
                "socks_proxy_port": sandbox_settings.network.socks_proxy_port,
            },
        }

    def _is_excluded_command(self, command: str, excluded: list[str]) -> bool:
        """检查命令是否匹配排除模式

        排除命令匹配逻辑：
        1. 拆分复合命令（&&, ||, ;, |）防止 safe_cmd && evil_cmd 绕过
        2. 逐个子命令：剥离环境变量前缀和安全包装器
        3. 匹配模式：prefix（前缀）、exact（精确）、wildcard（通配符）
        """
        if not excluded:
            return False

        # 拆分复合命令
        subcommands = re.split(r"\s*&&\s*|\s*\|\|\s*|\s*;\s*|\s*\|\s*", command)
        for sub in subcommands:
            sub = sub.strip()
            if not sub:
                continue
            # 剥离环境变量前缀 (FOO=bar cmd → cmd)
            cleaned = re.sub(r"^(\w+=\S+\s+)+", "", sub)
            # 剥离安全包装器
            for wrapper in ("sudo", "env", "time", "nice", "nohup"):
                if cleaned.startswith(wrapper + " "):
                    cleaned = cleaned[len(wrapper) + 1 :]
                    break
            # 匹配模式
            for pattern in excluded:
                # 精确匹配
                if cleaned == pattern:
                    return True
                # 通配符匹配（适用于所有模式，包括含 : 的模式）
                if fnmatch.fnmatch(cleaned, pattern):
                    return True
                # prefix 模式: "npm test:*" 中 "npm test" 匹配 "npm test:build"
                if ":" in pattern:
                    prefix = pattern.split(":")[0]
                    if cleaned == prefix or cleaned.startswith(prefix + " "):
                        return True
        return False
