"""
Goal 子系统
===========

goal 域状态机 + round driver + 模型工具；完成声明由单对抗性验证者
（复用 IllusionForge 自己的 verification 代理）复核。

主要组件：
    - GoalManager: goal 域状态机（manager.py）
    - run_goal_verification: 完成声明的对抗性验证编排（verifier.py）
    - 提示词原文（prompts.py）
"""

from illusion_forge.goal.manager import GoalManager
from illusion_forge.goal.types import (
    BLOCK_CODE_MODEL_REPORTED,
    BLOCK_CODE_ROUND_LIMIT,
    BLOCK_CODE_VERIFICATION_CAP,
    BLOCK_CODE_VERIFICATION_STALL,
    GoalActivation,
    GoalBlockReason,
    GoalError,
    GoalPersistedState,
    GoalPhase,
    GoalSettings,
    GoalSnapshot,
    GoalTurnSource,
    GoalView,
    PendingWrapup,
)
from illusion_forge.goal.verifier import (
    VerificationOutcome,
    gaps_fingerprint,
    parse_verdict,
    run_goal_verification,
)

__all__ = [
    "BLOCK_CODE_MODEL_REPORTED",
    "BLOCK_CODE_ROUND_LIMIT",
    "BLOCK_CODE_VERIFICATION_CAP",
    "BLOCK_CODE_VERIFICATION_STALL",
    "GoalActivation",
    "GoalBlockReason",
    "GoalError",
    "GoalManager",
    "GoalPersistedState",
    "GoalPhase",
    "GoalSettings",
    "GoalSnapshot",
    "GoalTurnSource",
    "GoalView",
    "PendingWrapup",
    "VerificationOutcome",
    "gaps_fingerprint",
    "parse_verdict",
    "run_goal_verification",
]
