"""CostTracker 单元测试。"""
from illusion_forge.api.usage import UsageSnapshot
from illusion_forge.engine.cost_tracker import CostTracker


def test_apply_restore_from_result() -> None:
    """apply_restore 从 RestoreResult 恢复 usage（含缓存分项）。"""
    from illusion_forge.engine.cost_tracker import CostTracker
    from illusion_forge.engine.messages import ConversationMessage
    from illusion_forge.services.checkpoint_store import RestoreResult

    result = RestoreResult(
        messages=[ConversationMessage.from_user_text("x")],
        usage_input=500,
        usage_output=50,
        usage_cache_read=1000,
        usage_cache_creation=200,
        last_usage=None,
        last_usage_message_count=0,
        checkpoint_count=1,
    )
    tracker = CostTracker()
    tracker.apply_restore(result)
    assert tracker.total.input_tokens == 500
    assert tracker.total.output_tokens == 50
    assert tracker.total.cache_read_input_tokens == 1000
    assert tracker.total.cache_creation_input_tokens == 200


def test_set_usage() -> None:
    """set_usage 直接设置累积值（含缓存分项默认 0）。"""
    from illusion_forge.engine.cost_tracker import CostTracker
    tracker = CostTracker()
    tracker.set_usage(300, 30)
    assert tracker.total.input_tokens == 300
    assert tracker.total.output_tokens == 30
    assert tracker.total.cache_read_input_tokens == 0
    assert tracker.total.cache_creation_input_tokens == 0
    tracker.set_usage(1, 2, cache_read_input_tokens=3, cache_creation_input_tokens=4)
    assert tracker.total.input_tokens == 1
    assert tracker.total.cache_read_input_tokens == 3
    assert tracker.total.cache_creation_input_tokens == 4


def test_add_accumulates_usage():
    tracker = CostTracker()
    tracker.add(UsageSnapshot(input_tokens=100, output_tokens=50))
    assert tracker.total.input_tokens == 100
    assert tracker.total.output_tokens == 50
    tracker.add(UsageSnapshot(input_tokens=200, output_tokens=100))
    assert tracker.total.input_tokens == 300
    assert tracker.total.output_tokens == 150


def test_add_accumulates_cache_tokens() -> None:
    """cache 分项随 add 累积。"""
    tracker = CostTracker()
    tracker.add(UsageSnapshot(
        input_tokens=100, output_tokens=50,
        cache_read_input_tokens=1000, cache_creation_input_tokens=200,
    ))
    tracker.add(UsageSnapshot(
        input_tokens=50, output_tokens=20,
        cache_read_input_tokens=500, cache_creation_input_tokens=0,
    ))
    assert tracker.total.input_tokens == 150
    assert tracker.total.output_tokens == 70
    assert tracker.total.cache_read_input_tokens == 1500
    assert tracker.total.cache_creation_input_tokens == 200


def test_initial_state_zero() -> None:
    tracker = CostTracker()
    assert tracker.total.input_tokens == 0
    assert tracker.total.output_tokens == 0
    assert tracker.total.cache_read_input_tokens == 0
    assert tracker.total.cache_creation_input_tokens == 0


def test_usage_snapshot_properties() -> None:
    """UsageSnapshot 的 total_input_tokens / context_size 计算。"""
    usage = UsageSnapshot(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=1000,
        cache_creation_input_tokens=200,
    )
    assert usage.total_input_tokens == 1300
    assert usage.context_size == 1350
    # 无缓存时的退化情况
    plain = UsageSnapshot(input_tokens=100, output_tokens=50)
    assert plain.total_input_tokens == 100
    assert plain.context_size == 150
