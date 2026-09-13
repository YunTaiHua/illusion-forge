"""沙箱平台抽象基类

定义各平台沙箱实现的统一接口。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SandboxPlatformConfig:
    """平台沙箱配置

    由 SandboxRuntime 从用户配置构建，传递给平台实现。

    Attributes:
        allow_write: 允许写入的路径列表
        deny_write: 拒绝写入的路径列表
        deny_read: 拒绝读取的路径列表
        allow_read: 在拒绝区域内重新允许读取的路径
        network_enabled: 是否启用网络限制
        http_proxy_port: HTTP 代理端口
        socks_proxy_port: SOCKS5 代理端口
        proxy_env: 代理环境变量
        allow_all_unix_sockets: 允许所有 Unix socket
        enable_weaker_nested_sandbox: Docker 环境跳过 --proc /proc
        enable_weaker_network_isolation: macOS 允许访问 trustd（降低网络隔离）
    """
    allow_write: list[str] = field(default_factory=lambda: ["."])
    deny_write: list[str] = field(default_factory=list)
    deny_read: list[str] = field(default_factory=list)
    allow_read: list[str] = field(default_factory=list)
    network_enabled: bool = False
    http_proxy_port: int | None = None
    socks_proxy_port: int | None = None
    proxy_env: dict[str, str] = field(default_factory=dict)
    allow_all_unix_sockets: bool = False
    enable_weaker_nested_sandbox: bool = False
    enable_weaker_network_isolation: bool = False


class SandboxPlatform(ABC):
    """沙箱平台抽象基类

    每个平台（Linux/macOS/Windows）实现此接口。
    """

    @abstractmethod
    def check_dependencies(self) -> list[str]:
        """检查平台依赖，返回缺失依赖的错误消息列表

        Returns:
            空列表表示所有依赖就绪
        """

    @abstractmethod
    def wrap_command(self, command: list[str], config: SandboxPlatformConfig) -> list[str]:
        """将命令包装为沙箱命令

        Args:
            command: 原始命令 argv
            config: 平台沙箱配置

        Returns:
            包装后的命令 argv
        """

    @abstractmethod
    def cleanup_after_command(self) -> None:
        """命令执行后的清理"""
