"""违规事件存储测试"""
from illusion_forge.sandbox.violation_store import SandboxViolation, SandboxViolationStore


def test_violation_store_add_and_get():
    store = SandboxViolationStore(max_size=5)
    v = SandboxViolation(line="deny file-write", command="rm -rf", encoded_command="cm0gLXJm", timestamp=1234567890)
    store.add_violation(v)
    assert store.get_count() == 1
    assert store.get_total_count() == 1
    violations = store.get_violations()
    assert len(violations) == 1
    assert violations[0].line == "deny file-write"


def test_violation_store_ring_buffer():
    store = SandboxViolationStore(max_size=3)
    for i in range(5):
        store.add_violation(SandboxViolation(line=f"v{i}", command="cmd", encoded_command="Y21k", timestamp=i))
    assert store.get_count() == 3
    assert store.get_total_count() == 5
    violations = store.get_violations()
    assert violations[0].line == "v2"
    assert violations[2].line == "v4"


def test_violation_store_subscribe():
    store = SandboxViolationStore()
    received = []
    unsub = store.subscribe(lambda v: received.append(len(v)))
    # subscribe 立即推送当前状态（空列表）
    assert received == [0]
    store.add_violation(SandboxViolation(line="test", command="cmd", encoded_command="Y21k", timestamp=1))
    assert received == [0, 1]  # 收到更新（1条违规）
    unsub()
    store.add_violation(SandboxViolation(line="test2", command="cmd", encoded_command="Y21k", timestamp=2))
    assert received == [0, 1]  # 已取消订阅，不再收到更新


def test_violation_store_get_for_command():
    store = SandboxViolationStore()
    store.add_violation(SandboxViolation(line="v1", command="rm -rf", encoded_command="cm0gLXJm", timestamp=1))
    store.add_violation(SandboxViolation(line="v2", command="ls", encoded_command="bHM=", timestamp=2))
    result = store.get_violations_for_command("cm0gLXJm")
    assert len(result) == 1
    assert result[0].command == "rm -rf"


def test_violation_store_clear():
    store = SandboxViolationStore()
    store.add_violation(SandboxViolation(line="v1", command="cmd", encoded_command="Y21k", timestamp=1))
    store.clear()
    assert store.get_count() == 0
    assert store.get_total_count() == 1  # total 不清零
