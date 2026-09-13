"""
Swarm 后端类型定义模块
=====================

本模块定义 Agent 派发功能使用的所有类型和协议。
包括后端类型、代理生成配置、消息类型等。

类型定义：
    - BackendType: 支持的后端类型
    - TeammateSpawnConfig: 代理生成配置
    - SpawnResult: 生成结果
    - TeammateMessage: 代理间消息

协议：
    - TeammateExecutor: 代理执行器协议

使用示例：
    >>> from illusion_forge.swarm.types import BackendType, TeammateExecutor, SpawnResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# 后端类型字面量
# ---------------------------------------------------------------------------

BackendType = Literal["subprocess", "in_process"]
"""所有支持的后端类型。"""


# ---------------------------------------------------------------------------
# 代理生成配置
# ---------------------------------------------------------------------------


@dataclass
class TeammateSpawnConfig:
    """生成代理的配置。"""

    name: str
    """人类可读的代理名称（例如 ``"researcher"``）。"""

    team: str
    """此代理所属的团队名称。"""

    prompt: str
    """代理的初始提示词/任务。"""

    cwd: str
    """代理的工作目录。"""

    parent_session_id: str
    """父会话 ID（用于转录关联）。"""

    model: str | None = None
    """此代理的模型覆盖。"""

    system_prompt: str | None = None
    """代理的系统提示词。"""

    system_prompt_mode: Literal["default", "replace", "append"] | None = None
    """如何应用系统提示词：替换或追加到默认。"""

    color: str | None = None
    """代理的可选 UI 颜色。"""

    color_override: str | None = None
    """明确的颜色覆盖（优先于 ``color``）。"""

    permissions: list[str] = field(default_factory=list)
    """授予此代理的工具权限。"""

    plan_mode_required: bool = False
    """此代理是否必须在实现前进入 plan 模式。"""

    allow_permission_prompts: bool = False
    """当为 False（默认）时，未列出的工具被自动拒绝。"""

    worktree_path: str | None = None
    """可选的 git worktree 路径，用于隔离的文件系统访问。"""

    session_id: str | None = None
    """明确的会话 ID（如果未提供则生成）。"""

    # 进程内代理执行所需上下文（由调用方传入，未传入时 _run_agent 回退到 stub）
    query_context: Any | None = None
    parent_registry: Any | None = None


# ---------------------------------------------------------------------------
# 生成结果和消息
# ---------------------------------------------------------------------------


@dataclass
class SpawnResult:
    """生成代理的结果。"""

    task_id: str
    """任务管理器中的任务 ID。"""

    agent_id: str
    """唯一代理标识符。"""

    backend_type: BackendType
    """用于生成此代理的后端。"""

    success: bool = True
    error: str | None = None


@dataclass
class TeammateMessage:
    """发送给代理的消息。"""

    text: str
    from_agent: str
    color: str | None = None
    timestamp: str | None = None
    summary: str | None = None


# ---------------------------------------------------------------------------
# TeammateExecutor 协议
# ---------------------------------------------------------------------------


@runtime_checkable
class TeammateExecutor(Protocol):
    """代理执行后端的协议。

    抽象化跨子进程和进程内后端的生成/消息/关闭操作。
    """

    type: BackendType

    def is_available(self) -> bool:
        """检查此后端在系统上是否可用。"""
        ...

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult:
        """使用给定配置生成新代理。"""
        ...

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None:
        """向运行中的代理发送消息。"""
        ...

    async def shutdown(self, agent_id: str, *, force: bool = False) -> bool:
        """终止代理。

        Args:
            agent_id: 要终止的代理。
            force: 如果为 True，立即杀死。如果为 False，尝试优雅关闭。

        Returns:
            如果代理成功终止返回 True。
        """
        ...
