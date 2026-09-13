"""GoalManager 状态机语义测试。"""

from __future__ import annotations

import pytest

from illusion_forge.goal.manager import GoalManager
from illusion_forge.goal.types import (
    BLOCK_CODE_MODEL_REPORTED,
    BLOCK_CODE_ROUND_LIMIT,
    GoalError,
    GoalSettings,
)


@pytest.fixture
def manager() -> GoalManager:
    return GoalManager(GoalSettings(
        default_max_goal_rounds=3,
        blocked_after_consecutive_rounds=2,
        verification_max_attempts=3,
    ))


@pytest.fixture
def created(manager: GoalManager) -> GoalManager:
    manager.current_source = "human"
    manager.create("Ship the feature", max_goal_rounds=3)
    return manager


def test_phase_transitions(created: GoalManager) -> None:
    view = created.get_view()
    assert view is not None
    assert view.snapshot.phase == "active"
    assert view.snapshot.revision == 1
    assert view.rounds_started == 0
    assert view.activation == "armed"

    # active → paused
    view = created.pause(view.snapshot.id, view.snapshot.revision)
    assert view.snapshot.phase == "paused"
    assert view.snapshot.revision == 2
    assert view.activation == "disarmed"

    # paused → active（resume 是唯一 rearm 途径）
    view = created.resume(view.snapshot.id, view.snapshot.revision)
    assert view.snapshot.phase == "active"
    assert view.activation == "armed"

    # active → complete
    view = created.complete(view.snapshot.id, view.snapshot.revision)
    assert view.snapshot.phase == "complete"
    assert view.activation == "disarmed"

    # complete 后不可再变更
    with pytest.raises(GoalError):
        created.pause(view.snapshot.id, view.snapshot.revision)
    with pytest.raises(GoalError):
        created.resume(view.snapshot.id, view.snapshot.revision)


def test_cas_revision_fence(created: GoalManager) -> None:
    view = created.get_view()
    assert view is not None
    # 携带过期 revision 的变更被拒绝
    with pytest.raises(GoalError):
        created.pause(view.snapshot.id, view.snapshot.revision + 1)
    with pytest.raises(GoalError):
        created.pause("wrong-id", view.snapshot.revision)
    # 正确 revision 生效
    created.pause(view.snapshot.id, view.snapshot.revision)
    assert created.snapshot is not None and created.snapshot.phase == "paused"


def test_authority_rules(manager: GoalManager) -> None:
    # 非 human 来源的 create 被拒
    manager.current_source = "goal"
    with pytest.raises(GoalError) as exc:
        manager.create("objective")
    assert exc.value.code == "GOAL_TOOL_AUTHORITY_REQUIRED"

    manager.current_source = "human"
    manager.create("objective")
    view = manager.get_view()
    assert view is not None

    # goal round 来源的 edit/pause/resume 被拒
    manager.current_source = "goal"
    with pytest.raises(GoalError):
        manager.edit(view.snapshot.id, view.snapshot.revision, objective="x")
    with pytest.raises(GoalError):
        manager.pause(view.snapshot.id, view.snapshot.revision)
    with pytest.raises(GoalError):
        manager.resume(view.snapshot.id, view.snapshot.revision)
    # goal round 来源的 complete/blocked 允许
    manager.complete(view.snapshot.id, view.snapshot.revision)


def test_blocked_threshold(created: GoalManager) -> None:
    view = created.get_view()
    assert view is not None
    # goal round 来源、未达门槛的 blocked 被机械拒绝
    manager = created
    manager.current_source = "goal"
    with pytest.raises(GoalError) as exc:
        manager.check_blocked_threshold()
    assert exc.value.code == "GOAL_TOOL_BLOCK_THRESHOLD"

    # 准入两轮后放行
    manager.current_source = "human"
    manager.admit_round()
    manager.admit_round()
    manager.current_source = "goal"
    manager.check_blocked_threshold()  # rounds_started=2 >= 2：不抛

    view = manager.get_view()
    assert view is not None
    result = manager.block(
        view.snapshot.id,
        view.snapshot.revision,
        code=BLOCK_CODE_MODEL_REPORTED,
        message="stuck on external API",
    )
    assert result.snapshot.phase == "blocked"
    assert result.snapshot.blocked_reason is not None
    assert result.snapshot.blocked_reason.code == BLOCK_CODE_MODEL_REPORTED


def test_round_limit_blocks(created: GoalManager) -> None:
    manager = created
    assert manager.admit_round() == 1
    assert manager.admit_round() == 2
    assert manager.admit_round() == 3
    # 上限耗尽：admit_round 返回 None 并自动 block('round-limit')
    assert manager.admit_round() is None
    assert manager.snapshot is not None
    assert manager.snapshot.phase == "blocked"
    assert manager.snapshot.blocked_reason is not None
    assert manager.snapshot.blocked_reason.code == BLOCK_CODE_ROUND_LIMIT


def test_should_continue_gate(manager: GoalManager) -> None:
    assert not manager.should_continue()
    manager.current_source = "human"
    manager.create("objective", max_goal_rounds=5)
    assert manager.should_continue()
    manager.disarm()
    assert not manager.should_continue()
    manager.current_source = "human"
    view = manager.get_view()
    assert view is not None
    manager.pause(view.snapshot.id, view.snapshot.revision)
    assert not manager.should_continue()


def test_edit_semantics(created: GoalManager) -> None:
    view = created.get_view()
    assert view is not None
    result = created.edit(view.snapshot.id, view.snapshot.revision, objective="New objective")
    assert result.snapshot.objective == "New objective"
    assert result.snapshot.revision == view.snapshot.revision + 1
    # 空白 objective 被拒
    view = created.get_view()
    assert view is not None
    with pytest.raises(GoalError):
        created.edit(view.snapshot.id, view.snapshot.revision, objective="   ")


def test_clear_tombstone(created: GoalManager) -> None:
    created.clear()
    assert created.snapshot is None
    assert created.get_view() is None
    assert not created.should_continue()


def test_persisted_roundtrip(created: GoalManager) -> None:
    created.admit_round()
    payload = created.persisted_state()
    assert payload is not None

    restored = GoalManager(GoalSettings())
    restored.restore_from(payload)
    assert restored.snapshot is not None
    assert restored.snapshot.id == created.snapshot.id  # type: ignore[union-attr]
    assert restored.rounds_started == 1
    # 恢复后 activation 恒为 disarmed
    assert restored.activation == "disarmed"
    assert not restored.should_continue()

    # clear 墓碑：persisted_state 返回 None
    created.clear()
    assert created.persisted_state() is None
