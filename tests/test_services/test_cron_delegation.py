"""cron_delegation 委托执行注册表测试。"""
from __future__ import annotations

import pytest

from illusion_forge.services import cron_delegation


@pytest.fixture(autouse=True)
def _clear_pending():
    """每个测试前清空委托队列。"""
    cron_delegation._pending.clear()
    yield
    cron_delegation._pending.clear()


@pytest.mark.asyncio
async def test_register_and_claim():
    """注册后可领取，且领取是原子的（弹出后不再可领）。"""
    job = {"id": "job1", "name": "t", "session_id": "s1", "prompt": "p"}
    cron_delegation.register_pending_job(job)
    claimed = cron_delegation.claim_pending()
    assert claimed == job
    assert cron_delegation.claim_pending() is None


@pytest.mark.asyncio
async def test_report_resolves_future():
    """上报结果 resolve future。"""
    job = {"id": "job1", "session_id": "s1"}
    fut = cron_delegation.register_pending_job(job)
    assert cron_delegation.report_result("job1", {"status": "success", "stdout": "ok"}) is True
    assert fut.result()["status"] == "success"
    assert fut.result()["stdout"] == "ok"


@pytest.mark.asyncio
async def test_report_after_claim_ignored():
    """任务被领取后上报应返回 False（无此任务）。"""
    job = {"id": "job1", "session_id": "s1"}
    cron_delegation.register_pending_job(job)
    cron_delegation.claim_pending()
    assert cron_delegation.report_result("job1", {"status": "success"}) is False


@pytest.mark.asyncio
async def test_report_not_supported_requeues():
    """not_supported 回报不 resolve future，且任务重新入队可再次领取。"""
    job = {"id": "job1", "session_id": "s1"}
    fut = cron_delegation.register_pending_job(job)

    assert cron_delegation.report_result("job1", {"status": "not_supported"}) is True
    assert not fut.done(), "not_supported 不应 resolve future"
    # 重新入队后可再次领取
    assert cron_delegation.claim_pending() == job


@pytest.mark.asyncio
async def test_reap_expired_resolves_unclaimed():
    """领取窗口耗尽后 reap 回收并 resolve unclaimed。"""
    job = {"id": "job1", "session_id": "s1"}
    fut = cron_delegation.register_pending_job(job)

    # 手动把条目标记为过期（绕过真实时间）
    cron_delegation._pending["job1"].deadline = 1.0

    reaped = cron_delegation.reap_expired()
    assert reaped == ["job1"]
    assert fut.result()["status"] == "unclaimed"
    assert cron_delegation.claim_pending() is None


@pytest.mark.asyncio
async def test_cancel_pending_removes_and_resolves():
    """cancel_pending 移除队列并 resolve unclaimed。"""
    job = {"id": "job1", "session_id": "s1"}
    fut = cron_delegation.register_pending_job(job)
    assert cron_delegation.cancel_pending("job1") is True
    assert fut.result()["status"] == "unclaimed"
    assert cron_delegation.claim_pending() is None


@pytest.mark.asyncio
async def test_cancel_pending_claimed_returns_false():
    """任务已被领取时 cancel_pending 返回 False（调用方应标记超时而非回退）。"""
    job = {"id": "job1", "session_id": "s1"}
    cron_delegation.register_pending_job(job)
    cron_delegation.claim_pending()
    assert cron_delegation.cancel_pending("job1") is False


@pytest.mark.asyncio
async def test_requeue_refreshes_deadline():
    """requeue 刷新领取截止时间。"""
    job = {"id": "job1", "session_id": "s1"}
    cron_delegation.register_pending_job(job)
    entry = cron_delegation._pending["job1"]
    old_deadline = entry.deadline
    assert cron_delegation.requeue("job1") is True
    assert entry.deadline >= old_deadline


@pytest.mark.asyncio
async def test_report_result_unknown_job():
    """上报未知任务返回 False。"""
    assert cron_delegation.report_result("nope", {"status": "success"}) is False


@pytest.mark.asyncio
async def test_claim_skips_expired_entry():
    """claim 跳过已过期条目（由 reap 回收）。"""
    job = {"id": "job1", "session_id": "s1"}
    cron_delegation.register_pending_job(job)
    cron_delegation._pending["job1"].deadline = 1.0  # 已过期
    assert cron_delegation.claim_pending() is None
    # 过期条目仍在队列，等 reap 回收
    assert "job1" in cron_delegation._pending
