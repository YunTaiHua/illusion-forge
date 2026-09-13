"""会话生命周期服务（唯一实现）
================================

Web 端会话的全部生命周期操作——创建、确保、恢复、删除、补位——
的唯一实现层。WebApiDispatcher 的各 web_* handler 是本服务的薄代理。

设计不变式（全部在本服务内保证，调用方无需关心）：
    1. 类型唯一权威：SessionRuntime.workbench 是会话类型的唯一内存权威，
       创建时由参数确定、恢复时从磁盘 meta 读回；空会话零磁盘痕迹。
    2. ensure_active 返回该类型"最近活跃"的会话——切换视图后切回来
       不会丢失之前的工作上下文。
    3. 删除补位：删除活跃会话后原子创建同类型新会话并激活。
    4. 驱逐保护：新创建/恢复中的会话不被自我淘汰。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from illusion_forge.services.file_history import cleanup_file_history
from illusion_forge.services.session_storage import (
    delete_session_by_id,
    list_session_snapshots,
    read_meta,
)
from illusion_forge.ui.web.session_runtime import SessionRuntime

if TYPE_CHECKING:
    from illusion_forge.ui.web.ws_host import WebBackendHost

log = logging.getLogger(__name__)


@dataclass
class LifecycleResult:
    """一次生命周期操作的结果。"""

    session: SessionRuntime
    """操作后的目标会话。"""

    replaced: bool = False
    """删除操作中活跃会话被删并已补位时为 True。"""

    deleted_ids: set[str] = field(default_factory=set)
    """删除操作实际成功的会话 ID。"""


class SessionLifecycleService:
    """Web 会话生命周期操作的唯一实现。"""

    def __init__(
        self,
        host: WebBackendHost,
        *,
        file_history_cleanup: Any | None = None,
    ) -> None:
        self._host = host
        self._file_history_cleanup = file_history_cleanup or (
            lambda sid: cleanup_file_history(sid)
        )
        # 每种类型最近活跃的会话 ID {True: wb_sid, False: chat_sid}
        # activate/create 时更新，ensure_active 据此找回
        self._last_active: dict[bool, str] = {}

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def active_session(self) -> SessionRuntime | None:
        return self._host._active_session()

    def get(self, session_id: str) -> SessionRuntime | None:
        return self._host._sessions.get(session_id)

    # ------------------------------------------------------------------
    # 确保：视图切换的原子操作
    # ------------------------------------------------------------------

    async def ensure_active(self, *, workbench: bool, cwd: str | None = None) -> SessionRuntime:
        """确保存在一个指定类型的活跃会话，返回它。

        活跃会话已是目标类型 → 直接返回（复用，不新建）。
        否则 → 找回该类型最近活跃的会话（内存/磁盘）→ 没有则创建。

        Args:
            workbench: 目标会话类型
            cwd: 目标工作区目录
        """
        host = self._host
        active = host._active_session()
        if active is not None and active.workbench == workbench:
            self._last_active[workbench] = active.session_id
            return active

        # 找回该类型最近活跃的会话（内存优先）
        last_sid = self._last_active.get(workbench)
        if last_sid:
            session = host._sessions.get(last_sid)
            if session is not None:
                host._set_active_session(session.session_id)
                return session
            # 已被驱逐：从磁盘恢复
            restored = await host._materialize_session(last_sid)
            if restored is not None:
                host._set_active_session(restored.session_id)
                return restored

        return await self.create(workbench=workbench, cwd=cwd)

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    async def create(self, *, workbench: bool, cwd: str | None = None) -> SessionRuntime:
        """创建全新的目标类型会话并激活。"""
        session = await self._host._create_session(cwd, workbench=workbench)
        self._host._set_active_session(session.session_id)
        self._last_active[workbench] = session.session_id
        return session

    # ------------------------------------------------------------------
    # 删除（含活跃会话补位）
    # ------------------------------------------------------------------

    async def delete_sessions(
        self,
        session_ids: list[str],
        *,
        delete_all: bool = False,
        cwd: str | None = None,
    ) -> LifecycleResult:
        """删除会话；若活跃会话被删则原子补位同类型新会话并激活。"""
        host = self._host
        busy_ids = {sr.session_id for sr in host._sessions.values() if sr.busy}
        active_session = host._active_session()
        scope_cwd = host._resolve_workspace_cwd(
            cwd or (active_session.bundle.cwd if active_session is not None else None)
        )

        # 捕获活跃会话类型（运行时权威；无运行时读磁盘兜底）
        active_workbench = False
        if host._active_session_id:
            if active_session is not None:
                active_workbench = active_session.workbench
            else:
                meta = await asyncio.to_thread(
                    read_meta, scope_cwd, host._active_session_id
                )
                wb_meta = await asyncio.to_thread(
                    read_meta, f"{scope_cwd}#wb", host._active_session_id
                )
                active_workbench = bool(
                    (meta or {}).get("workbench") or (wb_meta or {}).get("workbench")
                )

        # 计算删除目标
        if delete_all:
            sessions_chat = await asyncio.to_thread(list_session_snapshots, scope_cwd, 1000)
            sessions_wb = await asyncio.to_thread(list_session_snapshots, f"{scope_cwd}#wb", 1000)
            targets = [(scope_cwd, s["session_id"]) for s in sessions_chat if s["session_id"] not in busy_ids]
            # wb 树里只追加 chat 树中没有的会话（两棵树天然不重叠）
            existing_ids = {sid for _, sid in targets}
            targets += [(f"{scope_cwd}#wb", s["session_id"]) for s in sessions_wb
                         if s["session_id"] not in busy_ids and s["session_id"] not in existing_ids]
        else:
            def _locate(sids: list[str]) -> dict[str, str]:
                out: dict[str, str] = {}
                snapshot_sessions = dict(host._sessions)
                for sid in sids:
                    sess = snapshot_sessions.get(sid)
                    if sess is not None:
                        # 内存会话：workbench 类型决定存储树
                        scwd = f"{sess.bundle.cwd}#wb" if sess.workbench else sess.bundle.cwd
                        out[sid] = scwd
                        continue
                    for state in host._workspaces.values():
                        if read_meta(state.cwd, sid):
                            out[sid] = state.cwd
                            break
                        if read_meta(f"{state.cwd}#wb", sid):
                            out[sid] = f"{state.cwd}#wb"
                            break
                    out.setdefault(sid, scope_cwd)
                return out

            sid_cwds = await asyncio.to_thread(_locate, [s for s in session_ids if s not in busy_ids])
            targets = [(sid_cwds[sid], sid) for sid in session_ids if sid in sid_cwds]

        results = await asyncio.gather(
            *(asyncio.to_thread(delete_session_by_id, c, sid) for c, sid in targets),
            return_exceptions=True,
        )
        deleted_ids = {
            sid
            for (_c, sid), ok in zip(targets, results)
            if not isinstance(ok, Exception)
        }

        await asyncio.gather(
            *(asyncio.to_thread(self._file_history_cleanup, sid) for sid in deleted_ids),
            return_exceptions=True,
        )

        active_deleted = host._active_session_id in deleted_ids
        fallback_cwd = scope_cwd if active_session is None else active_session.bundle.cwd
        for sid in list(deleted_ids):
            if sid in host._sessions:
                await host._dispose_session(sid)

        if active_deleted:
            replacement = await host._create_session(fallback_cwd, workbench=active_workbench)
            host._set_active_session(replacement.session_id)
            self._last_active[active_workbench] = replacement.session_id
            return LifecycleResult(
                session=replacement, deleted_ids=deleted_ids, replaced=True,
            )

        keep = host._active_session()
        assert keep is not None
        return LifecycleResult(session=keep, deleted_ids=deleted_ids)
