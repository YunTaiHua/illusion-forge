"""
Goal 域类型模块
===============

主要组件：
    - GoalPhase: 目标相位字面量
    - GoalBlockReason: 受阻原因（code + message）
    - GoalSnapshot: 目标可持久快照（含 CAS revision 栅栏）
    - GoalActivation: 进程内激活状态（armed/disarmed，不持久化）
    - GoalPersistedState: checkpoint 持久化载荷
    - GoalError: 目标操作结构化错误
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

GoalPhase = Literal["active", "paused", "blocked", "complete"]
"""目标相位：active | paused | blocked | complete。"""

GoalActivation = Literal["armed", "disarmed"]
"""进程内激活状态（resume/fork 重启后恒为 disarmed，人类授权 resume 后 rearm）。"""

GoalTurnSource = Literal["human", "goal"]
"""当前轮次的消息来源：human（用户直接输入）或 goal（goal round 注入）。"""

# 阻塞原因 code 集合（round-limit / model-reported + 验证 cap / 停滞）
BLOCK_CODE_ROUND_LIMIT = "round-limit"
BLOCK_CODE_MODEL_REPORTED = "model-reported"
BLOCK_CODE_VERIFICATION_CAP = "verification-cap"
BLOCK_CODE_VERIFICATION_STALL = "verification-stall"


@dataclass(frozen=True)
class GoalBlockReason:
    """受阻原因。仅在 phase == 'blocked' 时存在。

    Attributes:
        code: 小写-kebab 原因码（round-limit / model-reported /
            verification-cap / verification-stall）
        message: 人类可读的具体阻塞条件
    """

    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> GoalBlockReason | None:
        if not data:
            return None
        return cls(code=str(data.get("code", "")), message=str(data.get("message", "")))


@dataclass(frozen=True)
class GoalSnapshot:
    """目标可持久快照。

    revision 是比较并交换（CAS）栅栏：每次可持久变更递增，
    变更操作必须携带调用方读到的精确 (id, revision)。

    Attributes:
        id: 目标 ID（'goal-<uuid>'）
        revision: CAS revision（从 1 起）
        objective: 完成目标文本
        phase: 当前相位
        blocked_reason: 受阻原因（仅 blocked 时存在）
        max_goal_rounds: 自动续跑轮次上限
    """

    id: str
    revision: int
    objective: str
    phase: GoalPhase
    blocked_reason: GoalBlockReason | None = None
    max_goal_rounds: int = 256

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "revision": self.revision,
            "objective": self.objective,
            "phase": self.phase,
            "max_goal_rounds": self.max_goal_rounds,
        }
        if self.blocked_reason is not None:
            data["blocked_reason"] = self.blocked_reason.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoalSnapshot:
        phase: GoalPhase = data.get("phase", "active")
        return cls(
            id=str(data.get("id", "")),
            revision=int(data.get("revision", 1)),
            objective=str(data.get("objective", "")),
            phase=phase,
            blocked_reason=GoalBlockReason.from_dict(data.get("blocked_reason")),
            max_goal_rounds=int(data.get("max_goal_rounds", 256)),
        )


@dataclass
class GoalPersistedState:
    """checkpoint 持久化的 goal 状态（last-wins 快照，非事件溯源）。

    activation / pending_wrapup / current_source 均为进程内状态，不持久化
    （恢复后 activation 恒为 disarmed）。

    Attributes:
        snapshot: 当前目标快照；None 表示无目标（创建前或 clear 之后）
        rounds_started: 已准入（admitted）的 goal round 数
        created_at: 创建时间戳（epoch 秒）
        updated_at: 最近一次变更时间戳
        verification_attempts: 验证拒绝累计次数（触发自动置 blocked 的计数）
        last_gaps: 最近一次验证回灌的缺陷文本
        last_fingerprint: 最近一次验证缺陷的指纹（停滞检测）
    """

    snapshot: GoalSnapshot | None = None
    rounds_started: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    verification_attempts: int = 0
    last_gaps: str = ""
    last_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any] | None:
        """序列化为 checkpoint 载荷；无目标时返回 None（clear 墓碑）。"""
        if self.snapshot is None:
            return None
        return {
            "snapshot": self.snapshot.to_dict(),
            "rounds_started": self.rounds_started,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "verification_attempts": self.verification_attempts,
            "last_gaps": self.last_gaps,
            "last_fingerprint": self.last_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> GoalPersistedState:
        if data is None:
            return cls()
        snapshot = data.get("snapshot")
        return cls(
            snapshot=GoalSnapshot.from_dict(snapshot) if snapshot else None,
            rounds_started=int(data.get("rounds_started", 0)),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            verification_attempts=int(data.get("verification_attempts", 0)),
            last_gaps=str(data.get("last_gaps", "")),
            last_fingerprint=data.get("last_fingerprint"),
        )


@dataclass
class GoalView:
    """目标的实时读取视图（快照 + 进程内状态）。"""

    snapshot: GoalSnapshot
    rounds_started: int
    created_at: float
    updated_at: float
    activation: GoalActivation


@dataclass
class PendingWrapup:
    """终态 wrap-up 待注入标记。

    Attributes:
        kind: 'complete' 或 'blocked'
        objective: 终态目标的 objective（渲染 wrap-up 提示用）
        blocked_reason: blocked 时的具体阻塞条件
    """

    kind: Literal["complete", "blocked"]
    objective: str
    blocked_reason: str | None = None


class GoalError(Exception):
    """目标操作结构化错误。

    code 错误码约定：
        - GOAL_TOOL_INVALID_UPDATE: 参数/CAS 校验失败
        - GOAL_TOOL_AUTHORITY_REQUIRED: 权威（human/goal-round）不足
        - GOAL_TOOL_BLOCK_THRESHOLD: blocked 早于最小轮次门槛
        - GOAL_TOOL_CONFLICT: 状态冲突（如目标已存在）
    """

    def __init__(self, message: str, code: str = "GOAL_TOOL_INVALID_UPDATE") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def now_ts() -> float:
    """当前 epoch 秒（便于测试注入）。"""
    return time.time()


@dataclass
class GoalSettings:
    """Goal 子系统运行配置（config/settings.py GoalSettings 的轻量镜像）。

    引擎持有该数据类以避免与 pydantic Settings 的循环依赖。
    """

    enabled: bool = True
    default_max_goal_rounds: int = 256
    blocked_after_consecutive_rounds: int = 3
    verification_enabled: bool = True
    verification_max_attempts: int = 10


__all__ = [
    "BLOCK_CODE_MODEL_REPORTED",
    "BLOCK_CODE_ROUND_LIMIT",
    "BLOCK_CODE_VERIFICATION_CAP",
    "BLOCK_CODE_VERIFICATION_STALL",
    "GoalActivation",
    "GoalBlockReason",
    "GoalError",
    "GoalPersistedState",
    "GoalPhase",
    "GoalSettings",
    "GoalSnapshot",
    "GoalTurnSource",
    "GoalView",
    "PendingWrapup",
    "now_ts",
]
