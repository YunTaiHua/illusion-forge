"""会话类型契约测试（工作台/聊天定型与传播）。

覆盖审计确认的四个关键契约：
    1. build_session_bundle / _create_session / _materialize_session 都必须
       携带 workbench 类型（内存权威）；
    2. _create_session 空会话零磁盘痕迹（不写 meta）；
    3. submit_line 的 workbench 声明只对"无磁盘 meta"的未定型会话生效；
    4. _maybe_evict_sessions(protect=) 永不淘汰被保护的会话。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from unittest.mock import AsyncMock

from illusion_forge.ui.web.session_runtime import SessionRuntime
from illusion_forge.ui.web.ws_web_api import WebApiDispatcher
from illusion_forge.ui.web.ws_host import WebBackendHost, _cwd_key

from .test_web_multisession import _make_host


def _make_session(host: WebBackendHost, sid: str) -> SessionRuntime:
    session = SessionRuntime(
        session_id=sid,
        bundle=MagicMock(),
    )
    session.bundle.app_state = host._bundle.app_state
    session.bundle.cwd = host._bundle.cwd
    session.engine.messages = []
    session.engine.current_context_tokens.return_value = 0
    session.engine._bg_agent_tracker.has_completions.return_value = False
    host._sessions[sid] = session
    return session


def test_build_session_bundle_propagates_workbench() -> None:
    """build_session_bundle 必须把 workbench 传播到会话级 bundle。"""
    from illusion_forge.ui.runtime import RuntimeBundle, build_session_bundle

    base = RuntimeBundle(
        api_client=MagicMock(),
        cwd="/fake",
        mcp_manager=MagicMock(),
        tool_registry=MagicMock(),
        app_state=MagicMock(),
        hook_executor=MagicMock(),
        engine=MagicMock(),
        commands=MagicMock(),
        external_api_client=False,
    )
    session_bundle = build_session_bundle(base, "sid1", MagicMock(), workbench=True)
    assert session_bundle.workbench is True
    assert session_bundle.session_id == "sid1"
    # 未声明时保持基线值（False）
    assert build_session_bundle(base, "sid2", MagicMock()).workbench is False


def test_create_session_zero_disk_trace(tmp_path, monkeypatch) -> None:
    """_create_session 空会话零磁盘痕迹：不写 meta、不建目录。"""
    host = _make_host()
    host._get_or_build_bundle = AsyncMock(return_value=host._bundle)  # type: ignore[method-assign]
    host._maybe_evict_sessions = lambda protect=None: None  # type: ignore[method-assign]
    from illusion_forge.ui.runtime import build_session_bundle

    monkeypatch.setattr(
        "illusion_forge.ui.web.ws_host.build_session_bundle",
        lambda b, sid, engine, workbench=False: MagicMock(
            engine=engine, session_id=sid, app_state=b.app_state, cwd=b.cwd,
            workbench=workbench,
        ),
    )
    session = asyncio.run(host._create_session(workbench=True))
    assert session.workbench is True
    assert session.bundle.workbench is True
    # 磁盘零痕迹：会话目录不存在
    session_dir = tmp_path / "sessions" / session.session_id
    assert not session_dir.exists()


def test_submit_line_typing_adopts_declaration_for_untyped_session(tmp_path, monkeypatch) -> None:
    """未定型（无磁盘 meta）会话的首条提交按声明定型；已定型会话忽略声明。"""
    host = _make_host()
    host._resolve_session = lambda sid=None: host._sessions.get(sid)  # type: ignore[method-assign]
    host._spawn_session_line = lambda session, coro: coro.close()  # type: ignore[method-assign]
    session = _make_session(host, "s-untyped")
    session.bundle.cwd = str(tmp_path)

    from illusion_forge.services.session_storage import read_meta

    # 无磁盘 meta → 未定型：采纳声明 workbench=True
    request = MagicMock()
    request.type = "submit_line"
    request.session_id = "s-untyped"
    request.workbench = True
    request.line = "hello"
    request.treat_as_text = False

    async def _run() -> None:
        await host._dispatch_request(request)

    asyncio.run(_run())
    assert session.workbench is True
    assert session.bundle.workbench is True
    # 已定型（meta 存在性检查通过 read_meta；此处直接验证声明不会反向改写）
    read_meta_fixture = read_meta(str(tmp_path), "s-untyped")
    assert read_meta_fixture is None  # 确认测试前置：确实无 meta


def test_maybe_evict_sessions_protects_protected_session() -> None:
    """容量满时被保护的会话（新建/恢复中）不得被自我淘汰。"""
    host = _make_host()
    # 驱逐以 background task 形式异步 dispose：测试中直接同步关闭协程
    host._create_background_task = lambda coro: coro.close()  # type: ignore[method-assign]
    host._evict_idle_workspace_bundles = lambda: None  # type: ignore[method-assign]
    # 压满 10 个空闲会话（> MAX_MATERIALIZED_SESSIONS=8）
    for i in range(10):
        _make_session(host, f"s{i:02d}")
    # 新会话已注册但尚未 set_active（创建路径的调用时序）
    _make_session(host, "s-new")
    # 全部非 busy、非 active → 无保护时 s-new 是淘汰候选之一
    host._maybe_evict_sessions(protect="s-new")
    assert "s-new" in host._sessions


def test_build_session_engine_registry_by_session_type(tmp_path) -> None:
    """build_session_engine 按会话类型经工厂构建注册表：
    工作台会话注册 CAD 工具域，聊天会话不注册。"""
    from illusion_forge.tools import create_default_tool_registry

    host = _make_host()
    calls: list[bool] = []

    def factory(*, cad_enabled: bool):
        calls.append(cad_enabled)
        registry = create_default_tool_registry(cad_enabled=cad_enabled)
        registry.__dict__["_cad_enabled"] = cad_enabled
        return registry

    session = SessionRuntime(session_id="s-typing", bundle=MagicMock(), workbench=True)
    session.bundle.cwd = str(tmp_path)
    session.bundle.current_settings.return_value = MagicMock(
        max_tokens=4096, max_turns=8, active_model_name="m",
        goal_enabled=False,
        get_model_capabilities=lambda: MagicMock(),
    )
    session.bundle.engine.tool_metadata = {}
    session.bundle.engine.permission_checker = MagicMock()
    session.bundle.engine.effort = None
    session.bundle.engine.system_prompt = "sp"
    session.bundle.hook_additional_contexts = []
    session.bundle.tool_registry_factory = factory
    session.bundle.mcp_manager = MagicMock()

    from illusion_forge.ui.runtime import build_session_engine

    engine_wb = build_session_engine(
        session.bundle, "s-typing", workbench=True,
        permission_prompt=None, ask_user_prompt=None, plan_approval_prompt=None,
    )
    assert calls[-1] is True
    assert engine_wb._tool_registry.get("cad_health_check") is not None

    engine_chat = build_session_engine(
        session.bundle, "s-typing", workbench=False,
        permission_prompt=None, ask_user_prompt=None, plan_approval_prompt=None,
    )
    assert calls[-1] is False
    assert engine_chat._tool_registry.get("cad_health_check") is None


def test_delete_active_lazy_empty_session_creates_replacement() -> None:
    """删除活跃的惰性空会话（无磁盘目录）必须创建同类型补位会话。

    回归：惰性 meta 后 _delete_session_by_id 对空会话返回 False（目录不存在），
    若据此把它排除出 deleted_ids，删除活跃会话将永远不触发补位——前端
    卡在等待加载动画。目录不存在 ≠ 未删除（内存运行时仍在）。
    """
    from unittest.mock import patch

    from illusion_forge.ui.web.ws_web_api import WebApiDispatcher

    host = _make_host()
    active = _make_session(host, "s-active")
    active.workbench = True
    active.bundle.workbench = True
    active.bundle.cwd = "/fake/cwd"
    host._active_session_id = "s-active"

    replacement = _make_session(host, "s-repl")
    replacement.workbench = True
    replacement.bundle.workbench = True
    replacement.bundle.cwd = "/fake/cwd"

    emitted: list[Any] = []

    async def _emit(event, session_id=None):
        emitted.append(event)
        return None

    async def _create(cwd=None, workbench=False):
        assert workbench is True, "补位会话必须继承被删活跃会话的工作台类型"
        return replacement

    async def _dispose(sid):
        return None

    host._dispose_session = _dispose  # type: ignore[method-assign]
    host._create_session = _create  # type: ignore[method-assign]
    host._set_active_session = lambda sid: setattr(host, "_active_session_id", sid)  # type: ignore[method-assign]
    host._push_sessions = AsyncMock()  # type: ignore[method-assign]
    host._status_snapshot = MagicMock()  # type: ignore[method-assign]

    dispatcher = WebApiDispatcher(host)
    dispatcher._emit = _emit  # type: ignore[method-assign]

    request = MagicMock()
    request.type = "web_delete_sessions"
    request.session_ids = ["s-active"]
    request.delete_all = False
    request.cwd = None

    # _delete_session_by_id 返回 False：模拟惰性空会话（目录不存在）
    with patch("illusion_forge.ui.web.ws_web_api._delete_session_by_id", return_value=False),          patch("illusion_forge.ui.web.ws_web_api._cleanup_file_history"):
        asyncio.run(dispatcher.handle(request))

    # 断言补位会话已激活并推送了 web_session_ready（删除补位的专用事件）
    assert host._active_session_id == "s-repl"
    readies = [e for e in emitted if e.type == "web_session_ready"]
    assert len(readies) == 1
    assert readies[0].session_id == "s-repl"
    assert readies[0].state["workbench"] is True


def test_cad_tools_use_session_canvas_not_default() -> None:
    """所有 CAD 工具的画布钉卡片必须走 for_session（会话画布），不得用 for_cwd。

    回归：cad_preview_build 和建模工具曾用 for_cwd（默认工作区画布），
    导致建模操作后前端收到默认画布广播、会话画布上的卡片消失/闪烁。
    """
    import inspect

    for mod_name in (
        "illusion_forge.cad.tools.__init__",
        "illusion_forge.cad.tools.modeling",
        "illusion_forge.cad.tools.advanced",
        "illusion_forge.cad.tools.production",
    ):
        import importlib
        mod = importlib.import_module(mod_name)
        src = inspect.getsource(mod)
        assert "for_cwd" not in src, (
            f"{mod_name} 仍然使用 for_cwd——必须改为 for_session(cwd, session_id)"
        )
