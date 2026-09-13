"""UI 层异步修复守护测试

覆盖 2 个修复点：
    1. ws_web_api.py: handle_web_delete_sessions 用 asyncio.gather + asyncio.to_thread 并行删除
    2. env_routes.py: OAuth 路由已用 asyncio.to_thread 包装（守护测试，防止回归）

测试策略：源码检查 + 行为测试混合，避免依赖真实 UI/网络。
"""
from __future__ import annotations

import inspect
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

# ─── Step 1: ws_web_api.py 批量删除异步化 ─────────────────────────


def test_ws_web_api_imports_asyncio():
    """ws_web_api 模块顶部导入 asyncio。"""
    from illusion_forge.ui.web import ws_web_api

    assert hasattr(ws_web_api, "asyncio"), "ws_web_api 模块必须导入 asyncio"


def test_handle_web_delete_sessions_uses_gather_and_to_thread():
    """handle_web_delete_sessions 用 asyncio.gather + asyncio.to_thread 并行删除。

    验证源码中存在 asyncio.gather 和 asyncio.to_thread(_delete_session_by_id, ...)，
    防止批量删除时事件循环被同步文件 I/O 阻塞。
    """
    from illusion_forge.ui.web.session_lifecycle import SessionLifecycleService
    from illusion_forge.ui.web.ws_web_api import WebApiDispatcher

    src = inspect.getsource(SessionLifecycleService.delete_sessions)
    assert "asyncio.gather" in src, (
        "delete_sessions 必须用 asyncio.gather 并行删除（逻辑已收敛到服务层）"
    )
    assert "asyncio.to_thread(delete_session_by_id" in src, (
        "delete_sessions 必须用 asyncio.to_thread 包装 delete_session_by_id"
    )
    assert "return_exceptions=True" in src, (
        "gather 必须用 return_exceptions=True 吞掉单个删除失败"
    )
    # 同步 for 循环调用 _delete_session_by_id 应已移除（裸 for x in sessions: _delete_...）
    assert "for s in sessions:" not in src, "delete_all 不应保留同步 for 循环"
    assert "for sid in request.session_ids:" not in src, (
        "session_ids 分支不应保留同步 for 循环"
    )


@pytest.mark.asyncio
async def test_handle_web_delete_sessions_calls_delete_in_threads(monkeypatch, tmp_path):
    """行为测试：delete_all 分支通过 to_thread 调用 _delete_session_by_id。

    mock _list_session_snapshots 返回 3 个会话，mock _delete_session_by_id 记录调用线程，
    验证删除在线程池中执行（线程名不同于主线程）。
    """
    from illusion_forge.ui.protocol import FrontendRequest
    from illusion_forge.ui.web.session_lifecycle import SessionLifecycleService
    from illusion_forge.ui.web.ws_web_api import WebApiDispatcher

    host = MagicMock()
    host._emit = AsyncMock()
    host._status_snapshot = MagicMock(return_value=MagicMock())
    host._bundle = MagicMock()
    host._bundle.cwd = str(tmp_path)
    host._bundle.session_id = "current-sid"
    host._bundle.app_state.get.return_value = MagicMock(ui_language="zh-CN")
    host._push_sessions = AsyncMock()
    host._dispose_session = AsyncMock()
    host._create_session = AsyncMock()
    host._session_state_payload = MagicMock(return_value={})
    host._sessions = {}
    host._active_session_id = "current-sid"

    dispatcher = WebApiDispatcher(host)

    main_thread = threading.current_thread()
    delete_calls: list[str] = []

    def fake_list(cwd, limit=20):
        return [{"session_id": f"s{i}"} for i in range(3)]

    def fake_delete(cwd, sid):
        # 记录调用线程名，验证不是主线程
        delete_calls.append(f"{sid}:{threading.current_thread().name}")
        return True

    monkeypatch.setattr(
        "illusion_forge.ui.web.session_lifecycle.list_session_snapshots", fake_list
    )
    monkeypatch.setattr(
        "illusion_forge.ui.web.session_lifecycle.delete_session_by_id", fake_delete
    )

    req = FrontendRequest(type="web_delete_sessions", delete_all=True)
    await dispatcher.handle(req)

    assert len(delete_calls) == 3, "delete_all 应删除全部 3 个会话"
    # 验证至少有一次删除发生在非主线程（to_thread 应使用线程池）
    main_thread_name = main_thread.name
    non_main_calls = [c for c in delete_calls if not c.endswith(f":{main_thread_name}")]
    assert len(non_main_calls) >= 1, (
        f"至少一次删除应在线程池中执行，主线程={main_thread_name}, 实际={delete_calls}"
    )


@pytest.mark.asyncio
async def test_handle_web_delete_sessions_swallows_individual_failures(monkeypatch, tmp_path):
    """行为测试：单个删除失败被 gather(return_exceptions=True) 吞掉，不传播异常。"""
    from illusion_forge.ui.protocol import FrontendRequest
    from illusion_forge.ui.web.session_lifecycle import SessionLifecycleService
    from illusion_forge.ui.web.ws_web_api import WebApiDispatcher

    host = MagicMock()
    host._emit = AsyncMock()
    host._status_snapshot = MagicMock(return_value=MagicMock())
    host._bundle = MagicMock()
    host._bundle.cwd = str(tmp_path)
    host._bundle.session_id = "current-sid"
    host._bundle.app_state.get.return_value = MagicMock(ui_language="zh-CN")
    host._push_sessions = AsyncMock()
    host._dispose_session = AsyncMock()
    host._create_session = AsyncMock()
    host._session_state_payload = MagicMock(return_value={})
    host._sessions = {}
    host._active_session_id = "current-sid"

    dispatcher = WebApiDispatcher(host)

    call_count = [0]

    def fake_delete(cwd, sid):
        call_count[0] += 1
        if sid == "fail-sid":
            raise OSError("disk full")
        return True

    monkeypatch.setattr(
        "illusion_forge.ui.web.session_lifecycle.list_session_snapshots", lambda cwd, limit=20: []
    )
    monkeypatch.setattr(
        "illusion_forge.ui.web.session_lifecycle.delete_session_by_id", fake_delete
    )

    req = FrontendRequest(
        type="web_delete_sessions",
        session_ids=["ok-sid-1", "fail-sid", "ok-sid-2"],
    )
    # 不应抛异常
    await dispatcher.handle(req)

    assert call_count[0] == 3, "所有 3 个删除应都被调用"
    # 删除后应推送刷新的会话列表（即使有失败）
    host._push_sessions.assert_awaited_once()


# ─── Step 4: env_routes.py OAuth 守护测试 ──────────────────────────


def test_env_routes_oauth_start_uses_to_thread():
    """oauth_start/oauth_poll 用 asyncio.to_thread 包装同步 OAuth 调用（防止回归）。"""
    from illusion_forge.ui.web.env_routes import register_env_routes

    # register_env_routes 内部定义闭包路由，需通过源码字符串检查
    src = inspect.getsource(register_env_routes)
    assert "asyncio.to_thread" in src, (
        "env_routes 必须用 asyncio.to_thread 包装同步 OAuth 调用"
    )
    assert "auth.start_device_flow" in src, "oauth_start 应调用 start_device_flow"
    assert "auth.poll_for_token" in src, "oauth_poll 应调用 poll_for_token"


def test_env_routes_does_not_use_requests():
    """env_routes 不应使用 requests 库（任务说明已确认走 asyncio.to_thread）。"""
    from illusion_forge.ui.web import env_routes

    src = inspect.getsource(env_routes)
    # 不应出现 requests.post/get 等同步 HTTP 调用
    assert "requests.post" not in src, "env_routes 不应使用 requests.post"
    assert "requests.get" not in src, "env_routes 不应使用 requests.get"
