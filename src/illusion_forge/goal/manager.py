"""
Goal 域管理器
=============

快照式状态机（非事件溯源）：所有可持久变更走 revision CAS，
持久化由引擎在轮次边界以 last-wins 快照行写入 checkpoint。

权威模型：
    - create / edit / pause / resume 要求 human 来源的轮次
    - complete / blocked 允许 human 或当前 goal round
    - resume 是唯一 rearm 途径（恢复/新建后 activation 恒为 disarmed）

主要类：
    - GoalManager: goal 域状态机
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from illusion_forge.goal.types import (
    BLOCK_CODE_ROUND_LIMIT,
    GoalActivation,
    GoalBlockReason,
    GoalError,
    GoalPersistedState,
    GoalSettings,
    GoalSnapshot,
    GoalTurnSource,
    GoalView,
    PendingWrapup,
    now_ts,
)

logger = logging.getLogger(__name__)


class GoalManager:
    """goal 域状态机（每个根会话引擎持有一个）。

    Attributes:
        dirty: 自上次持久化以来是否有可持久变更（引擎在轮次边界 flush）
    """

    def __init__(self, settings: GoalSettings | None = None) -> None:
        self._settings = settings or GoalSettings()
        self._state = GoalPersistedState()
        self._activation: GoalActivation = "disarmed"
        self._current_source: GoalTurnSource = "human"
        self._pending_wrapup: PendingWrapup | None = None
        self.dirty = False

    # ------------------------------------------------------------------
    # 只读视图
    # ------------------------------------------------------------------

    @property
    def snapshot(self) -> GoalSnapshot | None:
        """当前目标快照（只读）。"""
        return self._state.snapshot

    @property
    def rounds_started(self) -> int:
        return self._state.rounds_started

    @property
    def activation(self) -> GoalActivation:
        return self._activation

    @property
    def current_source(self) -> GoalTurnSource:
        """当前轮次的消息来源（由引擎在注入用户消息时设置）。"""
        return self._current_source

    @current_source.setter
    def current_source(self, value: GoalTurnSource) -> None:
        self._current_source = value

    @property
    def verification_attempts(self) -> int:
        return self._state.verification_attempts

    @property
    def last_gaps(self) -> str:
        return self._state.last_gaps

    @property
    def settings(self) -> GoalSettings:
        return self._settings

    def get_view(self) -> GoalView | None:
        """实时读取视图；无目标时 None。"""
        snap = self._state.snapshot
        if snap is None:
            return None
        return GoalView(
            snapshot=snap,
            rounds_started=self._state.rounds_started,
            created_at=self._state.created_at,
            updated_at=self._state.updated_at,
            activation=self._activation,
        )

    def goal_value(self) -> dict[str, object]:
        """GOAL_OUTPUT 紧凑 JSON（三个 goal 工具的共享输出格式）。"""
        view = self.get_view()
        if view is None:
            return {"goal": None}
        goal: dict[str, object] = {
            "id": view.snapshot.id,
            "revision": view.snapshot.revision,
            "objective": view.snapshot.objective,
            "phase": view.snapshot.phase,
            "roundsStarted": view.rounds_started,
            "maxGoalRounds": view.snapshot.max_goal_rounds,
        }
        if view.snapshot.blocked_reason is not None:
            goal["blockedReason"] = view.snapshot.blocked_reason.to_dict()
        return {"goal": goal, "activation": view.activation}

    def status_payload(self) -> dict[str, Any] | None:
        """前端状态栏载荷；无目标时 None。"""
        view = self.get_view()
        if view is None:
            return None
        payload: dict[str, Any] = {
            "id": view.snapshot.id,
            "revision": view.snapshot.revision,
            "objective": view.snapshot.objective,
            "phase": view.snapshot.phase,
            "roundsStarted": view.rounds_started,
            "maxGoalRounds": view.snapshot.max_goal_rounds,
            "activation": view.activation,
        }
        if view.snapshot.blocked_reason is not None:
            payload["blockedReason"] = view.snapshot.blocked_reason.to_dict()
        return payload

    # ------------------------------------------------------------------
    # 权威检查
    # ------------------------------------------------------------------

    def require_direct_human(self) -> None:
        """要求当前轮次来源为 human。"""
        if self._current_source != "human":
            raise GoalError(
                "this goal operation requires a direct human turn on a top-level agent",
                code="GOAL_TOOL_AUTHORITY_REQUIRED",
            )

    def require_completion_authority(self) -> None:
        """complete/blocked 要求 human 或当前 goal round。"""
        if self._current_source not in ("human", "goal"):
            raise GoalError(
                "complete and blocked require a direct human turn or the current goal round",
                code="GOAL_TOOL_AUTHORITY_REQUIRED",
            )

    # ------------------------------------------------------------------
    # CAS 校验
    # ------------------------------------------------------------------

    def _expect_current(self, goal_id: str, revision: int) -> GoalSnapshot:
        """校验 (goal_id, revision) 与当前快照精确匹配。

        CAS 不匹配时错误消息携带当前精确值，模型可不经 get_goal 直接重试
        （消除首次 update_goal 凭空猜测 id/revision 失败后的额外往返）。
        """
        snap = self._state.snapshot
        if snap is None:
            raise GoalError(
                "goal_id must be non-empty and revision must be a positive safe integer",
                code="GOAL_TOOL_INVALID_UPDATE",
            )
        if (
            not goal_id
            or goal_id != goal_id.strip()
            or snap.id != goal_id
            or snap.revision != revision
        ):
            raise GoalError(
                "goal_id/revision do not match the current goal revision; "
                f"the current goal is id={snap.id} revision={snap.revision} — "
                "retry update_goal with these exact values",
                code="GOAL_TOOL_INVALID_UPDATE",
            )
        return snap

    def _bump(self, snap: GoalSnapshot) -> GoalSnapshot:
        """递增 revision 并刷新 updated_at，返回新快照。"""
        return GoalSnapshot(
            id=snap.id,
            revision=snap.revision + 1,
            objective=snap.objective,
            phase=snap.phase,
            blocked_reason=snap.blocked_reason,
            max_goal_rounds=snap.max_goal_rounds,
        )

    # ------------------------------------------------------------------
    # 域操作
    # ------------------------------------------------------------------

    def create(self, objective: str, max_goal_rounds: int | None = None) -> GoalView:
        """创建目标（要求 human 权威；创建即 armed）。

        Args:
            objective: 完成目标文本（非空）
            max_goal_rounds: 可选轮次上限（正整数）

        Returns:
            GoalView: 创建后的视图

        Raises:
            GoalError: 目标已存在 / objective 为空 / 权威不足
        """
        self.require_direct_human()
        if self._state.snapshot is not None:
            raise GoalError(
                "a goal already exists in this session; clear it before creating another",
                code="GOAL_TOOL_CONFLICT",
            )
        trimmed = objective.strip() if objective else ""
        if not trimmed:
            raise GoalError(
                "objective must be a non-empty string",
                code="GOAL_TOOL_INVALID_UPDATE",
            )
        cap = max_goal_rounds if max_goal_rounds else self._settings.default_max_goal_rounds
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
            raise GoalError(
                "max_goal_rounds must be a positive safe integer",
                code="GOAL_TOOL_INVALID_UPDATE",
            )
        ts = now_ts()
        self._state = GoalPersistedState(
            snapshot=GoalSnapshot(
                id=f"goal-{uuid.uuid4()}",
                revision=1,
                objective=trimmed,
                phase="active",
                max_goal_rounds=cap,
            ),
            rounds_started=0,
            created_at=ts,
            updated_at=ts,
        )
        self._activation = "armed"
        self._pending_wrapup = None
        self.dirty = True
        return self.get_view()  # type: ignore[return-value]

    def edit(
        self,
        goal_id: str,
        revision: int,
        objective: str | None = None,
        max_goal_rounds: int | None = None,
    ) -> GoalView:
        """编辑目标（要求 human 权威；替换 objective / 轮次上限）。"""
        self.require_direct_human()
        snap = self._expect_current(goal_id, revision)
        if snap.phase == "complete":
            raise GoalError(
                "cannot edit a completed goal",
                code="GOAL_TOOL_INVALID_UPDATE",
            )
        new_objective = snap.objective
        if objective is not None and objective != "":
            new_objective = objective.strip()
            if not new_objective:
                raise GoalError(
                    "objective must be a non-empty string",
                    code="GOAL_TOOL_INVALID_UPDATE",
                )
        new_cap = snap.max_goal_rounds
        if max_goal_rounds:
            if not isinstance(max_goal_rounds, int) or isinstance(max_goal_rounds, bool) or max_goal_rounds < 1:
                raise GoalError(
                    "max_goal_rounds must be a positive safe integer",
                    code="GOAL_TOOL_INVALID_UPDATE",
                )
            new_cap = max_goal_rounds
        bumped = self._bump(snap)
        self._state.snapshot = GoalSnapshot(
            id=bumped.id,
            revision=bumped.revision,
            objective=new_objective,
            phase=bumped.phase,
            blocked_reason=None,
            max_goal_rounds=new_cap,
        )
        self._state.updated_at = now_ts()
        self.dirty = True
        return self.get_view()  # type: ignore[return-value]

    def pause(self, goal_id: str, revision: int) -> GoalView:
        """暂停目标（要求 human 权威；active → paused，disarm）。"""
        self.require_direct_human()
        snap = self._expect_current(goal_id, revision)
        if snap.phase != "active":
            raise GoalError(
                "pause requires the goal to be active",
                code="GOAL_TOOL_INVALID_UPDATE",
            )
        bumped = self._bump(snap)
        self._state.snapshot = GoalSnapshot(
            id=bumped.id,
            revision=bumped.revision,
            objective=bumped.objective,
            phase="paused",
            max_goal_rounds=bumped.max_goal_rounds,
        )
        self._state.updated_at = now_ts()
        self._activation = "disarmed"
        self.dirty = True
        return self.get_view()  # type: ignore[return-value]

    def resume(self, goal_id: str, revision: int) -> GoalView:
        """恢复目标（要求 human 权威；paused/blocked → active，rearm）。

        resume 是唯一 rearm 途径——会话恢复后 activation 恒为
        disarmed，人类以任何措辞要求继续时模型应调用 update_goal resume。
        """
        self.require_direct_human()
        snap = self._expect_current(goal_id, revision)
        if snap.phase not in ("paused", "blocked"):
            raise GoalError(
                "resume requires the goal to be paused or blocked",
                code="GOAL_TOOL_INVALID_UPDATE",
            )
        bumped = self._bump(snap)
        self._state.snapshot = GoalSnapshot(
            id=bumped.id,
            revision=bumped.revision,
            objective=bumped.objective,
            phase="active",
            max_goal_rounds=bumped.max_goal_rounds,
        )
        self._state.updated_at = now_ts()
        self._activation = "armed"
        self.dirty = True
        return self.get_view()  # type: ignore[return-value]

    def complete(self, goal_id: str, revision: int) -> GoalView:
        """标记完成（human 或当前 goal round；置 pending wrap-up）。"""
        self.require_completion_authority()
        snap = self._expect_current(goal_id, revision)
        if snap.phase == "complete":
            raise GoalError(
                "the goal is already complete",
                code="GOAL_TOOL_INVALID_UPDATE",
            )
        bumped = self._bump(snap)
        self._state.snapshot = GoalSnapshot(
            id=bumped.id,
            revision=bumped.revision,
            objective=bumped.objective,
            phase="complete",
            max_goal_rounds=bumped.max_goal_rounds,
        )
        self._state.updated_at = now_ts()
        self._activation = "disarmed"
        self.dirty = True
        return self.get_view()  # type: ignore[return-value]

    def block(
        self,
        goal_id: str | None,
        revision: int | None,
        code: str,
        message: str,
    ) -> GoalView:
        """标记受阻。goal_id/revision 为 None 时表示 harness 内部调用
        （round driver 的轮次上限、验证 cap/停滞），跳过 CAS 校验。

        Args:
            goal_id: 目标 ID（模型路径必填；内部路径可 None）
            revision: CAS revision（模型路径必填；内部路径可 None）
            code: 阻塞原因码
            message: 具体阻塞条件

        Returns:
            GoalView: 受阻后的视图
        """
        snap: GoalSnapshot | None
        if goal_id is not None and revision is not None:
            snap = self._expect_current(goal_id, revision)
        else:
            snap = self._state.snapshot
        if snap is None:
            raise GoalError(
                "no current goal to block",
                code="GOAL_TOOL_INVALID_UPDATE",
            )
        if snap.phase == "complete":
            raise GoalError(
                "cannot block a completed goal",
                code="GOAL_TOOL_INVALID_UPDATE",
            )
        bumped = self._bump(snap)
        self._state.snapshot = GoalSnapshot(
            id=bumped.id,
            revision=bumped.revision,
            objective=bumped.objective,
            phase="blocked",
            blocked_reason=GoalBlockReason(code=code, message=message),
            max_goal_rounds=bumped.max_goal_rounds,
        )
        self._state.updated_at = now_ts()
        self._activation = "disarmed"
        self.dirty = True
        return self.get_view()  # type: ignore[return-value]

    def clear(self, goal_id: str | None = None, revision: int | None = None) -> None:
        """清除目标（写墓碑；人类命令路径专用，要求 human 权威）。"""
        self.require_direct_human()
        if self._state.snapshot is not None:
            if goal_id is not None and revision is not None:
                self._expect_current(goal_id, revision)
            elif self._state.snapshot is not None:
                # 无 CAS 参数的 /goal clear：按当前快照直接清除
                pass
        self._state = GoalPersistedState()
        self._activation = "disarmed"
        self._pending_wrapup = None
        self.dirty = True

    def disarm(self) -> None:
        """进程内 disarm（不产生可持久变更；max-tokens/错误时驱动器停摆）。"""
        self._activation = "disarmed"

    def check_blocked_threshold(self) -> None:
        """GOAL_TOOL_BLOCK_THRESHOLD 检查：goal round 来源下，
        blocked 早于 blocked_after_consecutive_rounds 轮时机械拒绝。"""
        if (
            self._current_source == "goal"
            and self._state.snapshot is not None
            and self._state.rounds_started < self._settings.blocked_after_consecutive_rounds
        ):
            raise GoalError(
                f"blocked requires at least "
                f"{self._settings.blocked_after_consecutive_rounds} consecutive goal "
                f"rounds; current round is {self._state.rounds_started}",
                code="GOAL_TOOL_BLOCK_THRESHOLD",
            )

    # ------------------------------------------------------------------
    # Round driver
    # ------------------------------------------------------------------

    def should_continue(self) -> bool:
        """是否应再注入一个 goal round（active + armed + 未达上限 + 无待 wrap-up）。"""
        snap = self._state.snapshot
        if snap is None or self._pending_wrapup is not None:
            return False
        return (
            snap.phase == "active"
            and self._activation == "armed"
            and self._state.rounds_started < snap.max_goal_rounds
        )

    def admit_round(self) -> int | None:
        """准入下一个 goal round（rounds_started += 1）。

        Returns:
            int: 新 round 编号；轮次已耗尽时先 block('round-limit') 并返回 None
        """
        snap = self._state.snapshot
        if snap is None or snap.phase != "active" or self._activation != "armed":
            return None
        if self._state.rounds_started >= snap.max_goal_rounds:
            self.block(
                None,
                None,
                code=BLOCK_CODE_ROUND_LIMIT,
                message=(
                    f"Goal round limit reached (max {snap.max_goal_rounds} rounds); "
                    "goal auto-paused"
                ),
            )
            return None
        self._state.rounds_started += 1
        self.dirty = True
        return self._state.rounds_started

    def take_pending_wrapup(self) -> PendingWrapup | None:
        """取出并清除待注入的 wrap-up（引擎注入 <goal_complete>/<goal_blocked>）。"""
        wrapup = self._pending_wrapup
        self._pending_wrapup = None
        return wrapup

    def set_pending_wrapup(self, wrapup: PendingWrapup | None) -> None:
        """设置待注入的 wrap-up（update_goal 终态路径调用）。"""
        self._pending_wrapup = wrapup

    # ------------------------------------------------------------------
    # 验证簿记（attempts / gaps / 停滞指纹）
    # ------------------------------------------------------------------

    def record_verification_rejection(self, gaps: str, fingerprint: str) -> None:
        """记录一次验证拒绝。"""
        self._state.verification_attempts += 1
        self._state.last_gaps = gaps
        self._state.last_fingerprint = fingerprint
        self.dirty = True

    def record_verification_success(self) -> None:
        """验证通过后清空簿记。"""
        self._state.verification_attempts = 0
        self._state.last_gaps = ""
        self._state.last_fingerprint = None
        self.dirty = True

    def same_fingerprint_as_last(self, fingerprint: str) -> bool:
        """停滞检测：本次缺陷指纹与上次拒绝是否相同。"""
        return (
            self._state.last_fingerprint is not None
            and self._state.last_fingerprint == fingerprint
        )

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def persisted_state(self) -> dict[str, Any] | None:
        """导出 last-wins 持久化载荷（无目标时 None）。"""
        if self.dirty:
            self._state.updated_at = now_ts()
        self.dirty = False
        return self._state.to_dict()

    def restore_from(self, data: dict[str, Any] | None) -> None:
        """从 checkpoint 恢复（恢复后 activation 恒为 disarmed）。"""
        self._state = GoalPersistedState.from_dict(data)
        self._activation = "disarmed"
        self._pending_wrapup = None
        self._current_source = "human"
        self.dirty = False

    def reset(self) -> None:
        """完全清空（/new、full_reset）。"""
        self._state = GoalPersistedState()
        self._activation = "disarmed"
        self._pending_wrapup = None
        self._current_source = "human"
        self.dirty = False
