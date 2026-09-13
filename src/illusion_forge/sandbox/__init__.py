"""沙箱模块公共 API

提供沙箱系统的统一入口：
- SandboxManager: 沙箱管理器单例
- SandboxRuntime: 核心运行时
- SandboxViolationStore: 违规事件存储
- SandboxAvailability: 可用性状态
- SandboxUnavailableError: 不可用异常
"""
from illusion_forge.sandbox.adapter import (
    SandboxAvailability,
    SandboxManager,
    SandboxUnavailableError,
)
from illusion_forge.sandbox.runtime import SandboxRuntime
from illusion_forge.sandbox.violation_store import SandboxViolation, SandboxViolationStore

__all__ = [
    "SandboxAvailability",
    "SandboxManager",
    "SandboxRuntime",
    "SandboxUnavailableError",
    "SandboxViolation",
    "SandboxViolationStore",
]
