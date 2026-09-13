"""SolidWorks COM 会话宿主（STA 线程）
================================

把全部 SolidWorks COM 操作收敛到一条专用 STA 线程，规避跨单元封送问题。

设计要点：
    - 线程模型：专用线程 ``pythoncom.CoInitialize()`` + 串行任务队列，
      工具侧只收发纯数据
    - 超时语义：COM 调用不可强杀；超时返回 ``cad_busy``，任务继续执行
    - 重启契约：线程死亡重启时清空全部 COM 指针，避免悬挂引用
    - 文档身份：``(GetTitle, GetPathName)`` 二元组，切换文档自动失效
      Motion Study 等文档级状态
    - 可视化：每操作后广播 ``{状态, 文档, 特征树, 快照帧, 选中项}``

主要组件：
    - SolidWorksHost: 进程级单例宿主（线程 + 队列 + 会话状态）
    - CadHostError: 带错误码的操作错误

使用示例：
    >>> host = SolidWorksHost.instance()
    >>> result = await host.run("cad_op", lambda h: h.state())
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import queue
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from illusion_forge.cad.events import broadcast_cad_update

log = logging.getLogger(__name__)

try:  # pywin32 专属环境符号；非 Windows 下 host 本就不可用
    from pywintypes import com_error
except ImportError:  # pragma: no cover
    com_error = Exception  # type: ignore[assignment,misc]

#: 常规操作超时（大模型 rebuild 通常 < 60s，留余量）
DEFAULT_OP_TIMEOUT = 120.0
#: 连接/启动 SolidWorks 的超时（冷启动 + 许可校验可能很慢）
CONNECT_TIMEOUT = 300.0
#: 特征树事件的最大节点数（防超大装配撑爆事件载荷）
TREE_LIMIT = 300
#: 每次快照保留的最大条目数（环形截断，文件不删）
SNAPSHOT_HISTORY_LIMIT = 200
#: 空闲时轮询用户选中项/活动文档的间隔（秒；配合 0.5s 队列 get 超时）
SELECTION_POLL_INTERVAL = 2.0
#: 单次上报的选中项上限
SELECTION_ITEMS_LIMIT = 20


class CadHostError(RuntimeError):
    """CAD 宿主操作错误（携带机器可读 code，供模型自纠错）。"""

    def __init__(self, message: str, code: str = "cad_host_error") -> None:
        super().__init__(message)
        self.code = code


class _Job:
    """宿主队列任务。"""

    __slots__ = ("enqueued_at", "fn", "future", "label", "timeout")

    def __init__(self, label: str, fn: Callable[[SolidWorksHost], Any],
                 future: concurrent.futures.Future[object], timeout: float) -> None:
        self.label = label
        self.fn = fn
        self.future = future
        self.timeout = timeout
        self.enqueued_at = datetime.now().astimezone()




def _sw_instance_dead(sw: Any) -> bool:
    """判断 ISldWorks COM 指针是否已失效（实例被关闭）。

    无打开文档时 ActiveDoc 抛 AttributeError，但应用级成员（如 RevId）
    仍可访问；实例关闭则连应用级成员都失败。
    """
    from illusion_forge.cad.vendor.sw_connect import get_com_member

    try:
        get_com_member(sw, "RevId")
        return False
    except (AttributeError, com_error):
        # COM 层任何失败（未注册/实例已死）都视为"不可探测"
        return True

class SolidWorksHost:
    """进程级单例：STA 线程 + 任务队列 + 会话状态。"""

    _instance: SolidWorksHost | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[_Job] = queue.Queue()
        self._stop = False
        # 以下字段跨线程读写（仅简单赋值/读取，GIL 下安全；不承载数据结构不变量）
        self._sw: Any = None            # ISldWorks，仅宿主线程使用
        self._owned = False             # 是否由我们 Dispatch 启动（决定能否退出）
        self._busy_label: str | None = None
        self._last_error: str | None = None
        self._snapshots: list[dict[str, Any]] = []
        self._modules: dict[str, Any] = {}
        self._modules_loaded = False
        # 选中项/文档轮询（M3 协作回流）：缓存最近一次快照，变化才广播
        self._selection_info: dict[str, Any] | None = None
        self._selection_cache: dict[str, Any] | None = None
        self._last_poll_at: float = 0.0
        self._last_document_info: dict[str, Any] | None = None
        # Motion Study 槽位（COM 对象仅宿主线程可用，跨工具调用复用）
        self.last_motion_study: Any = None
        # _snapshots 跨线程读写锁：宿主线程写（append+截断），其他线程读
        # （latest_snapshot/snapshot_history）——不依赖 CPython GIL 的实现细节
        self._snapshots_lock = threading.Lock()

    @classmethod
    def instance(cls) -> SolidWorksHost:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # === asyncio 侧入口 ===

    async def run(self, label: str, fn: Callable[[SolidWorksHost], Any],
                  timeout: float = DEFAULT_OP_TIMEOUT) -> Any:
        """提交任务并在宿主线程执行，await 其结果。

        Args:
            label: 操作名（busy 状态/事件载荷展示用）
            fn: 在宿主线程执行的闭包，接收宿主实例
            timeout: 等待结果的超时秒数；超时后调用方得到 cad_busy 错误，
                任务本身继续执行（COM 不可强杀）

        Raises:
            CadHostError: 任务执行失败（原样转发线程内异常）或等待超时
        """
        self._ensure_thread()
        job = _Job(label=label, fn=fn, future=concurrent.futures.Future(), timeout=timeout)
        self._queue.put(job)
        asyncio_future = asyncio.wrap_future(job.future)
        try:
            return await asyncio.wait_for(asyncio_future, timeout=timeout)
        except asyncio.TimeoutError:
            raise CadHostError(
                f"操作 {label!r} 等待 {timeout:.0f}s 未完成：SolidWorks 可能正忙"
                "（大模型 rebuild / 模态对话框）。任务仍在后台执行；如长时间无响应请在外部关闭 SolidWorks 后重试。",
                "cad_busy",
            ) from None

    def state(self) -> dict[str, Any]:
        """会话状态快照（asyncio 侧可安全读取）。"""
        return {
            "connected": self._sw is not None,
            "owned": self._owned,
            "busy_label": self._busy_label,
            "last_error": self._last_error,
            "snapshot_count": len(self._snapshots),
        }

    def latest_snapshot(self) -> dict[str, Any] | None:
        return self._snapshots[-1] if self._snapshots else None

    # === 宿主线程 ===

    def _ensure_thread(self) -> None:
        """确保宿主线程存活；线程死亡后重启并失效全部 COM 状态。

        重启契约：STA 线程一旦死亡（不可恢复的 COM 异常等），其 apartment
        里的全部 COM 指针（``_sw``/``last_motion_study``）随之失效——重启
        前必须清空，否则新线程会拿到悬挂指针。后续任务会在新线程里得到
        明确的 ``cad_not_connected`` 错误而非难排查的 COM 崩溃。
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._sw = None
        self._owned = False
        self.last_motion_study = None
        self._modules_loaded = False
        self._stop = False
        self._thread = threading.Thread(target=self._thread_main, name="illusion-cad-sta", daemon=True)
        self._thread.start()

    def _thread_main(self) -> None:
        pythoncom: Any = None
        try:
            import pythoncom as _pythoncom

            pythoncom = _pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            # pywin32 缺失：任务会在 _modules() 处得到明确错误，不在此处崩溃
            log.warning("pywin32 不可用，SolidWorks COM 宿主无法初始化")
        try:
            while not self._stop:
                try:
                    job = self._queue.get(timeout=0.5)
                except queue.Empty:
                    # 空闲期协作回流：轮询用户在 SolidWorks 中的选中项/活动
                    # 文档，变化才广播（M3 选中项回流）
                    if self._sw is not None:
                        try:
                            self._poll_selection()
                        except Exception:
                            log.debug("选中项轮询失败", exc_info=True)
                    continue
                self._busy_label = job.label
                try:
                    result = job.fn(self)
                    if not job.future.done():
                        job.future.set_result(result)
                except Exception as exc:
                    # 看门狗语义：必须捕获一切以回传 future 并保住 STA 线程
                    log.exception("CAD 宿主任务失败: %s", job.label)
                    self._last_error = f"{job.label}: {exc}"
                    if not job.future.done():
                        job.future.set_exception(exc)
                finally:
                    self._busy_label = None
                    try:
                        self._emit_update(label=job.label)
                    except Exception:
                        log.debug('CAD 边界操作失败', exc_info=True)
                        # 退出，后续所有任务将永远排队直到超时
                        log.exception("cad_update 载荷构建失败（已忽略）")
        finally:
            if pythoncom is not None:
                pythoncom.CoUninitialize()

    # === vendored 模块懒加载（仅宿主线程调用） ===

    def modules(self) -> dict[str, Any]:
        """惰性导入 vendored sw_* 模块（import 时初始化 pywin32）。"""
        if not self._modules_loaded:
            try:
                from illusion_forge.cad.vendor import (
                    sw_appearance,
                    sw_assembly,
                    sw_connect,
                    sw_delivery,
                    sw_document_data,
                    sw_drawing,
                    sw_export,
                    sw_hole_features,
                    sw_motion,
                    sw_part,
                    sw_review,
                    sw_sheet_metal,
                    sw_weldment,
                )
            except Exception as exc:
                raise CadHostError(
                    f"SolidWorks COM 依赖不可用（pywin32/comtypes 未安装或初始化失败）: {exc}",
                    "cad_com_unavailable",
                ) from exc
            self._modules = {
                "connect": sw_connect,
                "part": sw_part,
                "assembly": sw_assembly,
                "hole": sw_hole_features,
                "docdata": sw_document_data,
                "review": sw_review,
                "export": sw_export,
                # M3 二期
                "delivery": sw_delivery,
                "motion": sw_motion,
                "appearance": sw_appearance,
                "drawing": sw_drawing,
                # M4 深化
                "sheetmetal": sw_sheet_metal,
                "weldment": sw_weldment,
            }
            self._modules_loaded = True
        return self._modules

    # === 会话管理（仅宿主线程调用） ===

    @property
    def sw(self) -> Any:
        """ISldWorks 实例（未连接时抛错）。"""
        if self._sw is None:
            raise CadHostError("尚未连接 SolidWorks，请先调用 cad_connect。", "cad_not_connected")
        return self._sw

    @property
    def model(self) -> Any:
        """活动文档 IModelDoc2（cad_python 便捷入口；仅宿主线程内使用）。

        未连接或无打开文档时返回 None（不抛错，方便 agent 探测）。
        """
        return self.active_model(required=False)

    def connect(self, version: str | None = None, visible: bool = True) -> dict[str, Any]:
        """附着已有 SolidWorks 实例（优先）或启动新实例。

        指定版本的 ProgID（如 SldWorks.Application.30）可能因旧版本
        卸载残留而未注册——此时自动回退到无版本号 ProgID（指向本机
        最新可用版本）重试一次，失败信息中注明已回退。
        """
        connect = self.modules()["connect"]
        try:
            sw, _model, metadata = connect.connect_solidworks(
                version=version, wait_seconds=10, visible=visible, return_metadata=True
            )
        except Exception as exc:
            if version is None:
                raise
            from illusion_forge.cad.vendor.sw_connect import SolidWorksConnectionError

            if not isinstance(exc, SolidWorksConnectionError):
                raise
            metadata = {}
            sw, _model, metadata = connect.connect_solidworks(
                version=None, wait_seconds=10, visible=visible, return_metadata=True
            )
            if isinstance(metadata, dict):
                metadata["version_fallback"] = True
                metadata.setdefault("limitations", []).append(
                    f"版本 {version} 的 ProgID 未注册，已自动回退到本机最新可用版本"
                )
        self._sw = sw
        self._owned = bool(metadata.get("launched_here")) if isinstance(metadata, dict) else False
        return metadata if isinstance(metadata, dict) else {}

    def active_model(self, required: bool = True) -> Any:
        """返回活动文档 IModelDoc2（无打开文档时为 None / 抛错）。"""
        from illusion_forge.cad.vendor.sw_connect import get_com_member

        if self._sw is None:
            if required:
                raise CadHostError("尚未连接 SolidWorks，请先调用 cad_connect。", "cad_not_connected")
            return None
        try:
            model = get_com_member(self._sw, "ActiveDoc")
        except Exception as exc:
            # 两种情况均为正常状态，返回 None：
            # - 无打开文档：pywin32 动态派发对 ActiveDoc 抛 AttributeError
            # - SolidWorks 关闭中：com_error
            # 区分"实例已失效"（_sw 指向死 COM 对象）：连 _sw 自身成员都
            # 访问失败时清空会话状态，后续调用得到明确的 cad_not_connected，
            # 而不是每个任务后的 _emit_update 反复抛 AttributeError。
            if _sw_instance_dead(self._sw):
                self._sw = None
                self._owned = False
                self.last_motion_study = None
                if required:
                    raise CadHostError(
                        "SolidWorks 实例已关闭（COM 对象失效），请重新 cad_connect。",
                        "cad_not_connected",
                    ) from exc
            model = None
        if model is None and required:
            raise CadHostError("SolidWorks 中没有打开的文档，请先 cad_new_document 或 cad_open_document。", "cad_no_document")
        return model

    def capture_snapshot(self, artifacts_dir: Path, label: str,
                         views: tuple[str, ...] = ("isometric",)) -> list[dict[str, Any]]:
        """导出当前模型快照帧（线程内调用；失败静默降级，不阻塞操作）。"""
        review = self.modules()["review"]
        model = self.active_model(required=False)
        if model is None:
            return []
        out_dir = Path(artifacts_dir) / "snapshots"
        created: list[dict[str, Any]] = []
        for view in views:
            stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            path = out_dir / f"frame_{stamp}_{view}.bmp"
            try:
                review.save_preview(model, str(path), view_name=view, width=960, height=600)
            except (RuntimeError, OSError, AttributeError, com_error) as exc:
                log.warning("快照导出失败 view=%s: %s", view, exc)
                continue
            entry = {
                "path": str(path),
                "view": view,
                "label": label,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            with self._snapshots_lock:
                self._snapshots.append(entry)
                if len(self._snapshots) > SNAPSHOT_HISTORY_LIMIT:
                    del self._snapshots[:-SNAPSHOT_HISTORY_LIMIT]
            created.append(entry)
        return created

    def snapshot_history(self) -> list[dict[str, Any]]:
        """返回快照历史（最近在前，供 web_cad_status / 分镜流）。"""
        with self._snapshots_lock:
            recent = self._snapshots[-50:]
        return list(reversed(recent))

    def quit_owned(self) -> bool:
        """退出由我们启动的 SolidWorks 实例（线程内调用）。

        Returns:
            bool: 是否执行了退出；附着实例（非本进程启动）返回 False
        """
        if self._sw is None:
            return False
        if not self._owned:
            return False
        connect = self.modules()["connect"]
        connect.close_owned_solidworks(self._sw, True)
        self._sw = None
        self._owned = False
        return True

    # === 选中项回流（线程内调用） ===

    def selection_info(self) -> dict[str, Any] | None:
        """返回最近缓存的选中项/活动文档快照（线程安全读取）。"""
        return self._selection_info

    def _poll_selection(self) -> None:
        """轮询活动文档与用户选中项，变化才更新缓存并广播。

        文档身份 = (GetTitle, GetPathName)：仅凭标题会在"关闭文档 A 后
        打开同名文档 B"时漏检，导致 Motion Study 等文档级 COM 槽位悬挂。
        """
        import time as _time

        from illusion_forge.cad.vendor.sw_connect import get_com_member

        now = _time.monotonic()
        if now - self._last_poll_at < SELECTION_POLL_INTERVAL:
            return
        self._last_poll_at = now
        prev_identity = (self._selection_cache or {}).get("_doc_identity")
        model = self.active_model(required=False)
        info: dict[str, Any] | None = None
        if model is not None:
            doc_title, doc_path = "", ""
            try:
                doc_title = str(get_com_member(model, "GetTitle") or "")
            except Exception:
                log.debug('COM 成员探测失败', exc_info=True)
            try:
                doc_path = str(get_com_member(model, "GetPathName") or "")
            except Exception:
                log.debug('COM 成员探测失败', exc_info=True)
            items: list[dict[str, Any]] = []
            count = 0
            try:
                sel_mgr = get_com_member(model, "SelectionManager")
                raw_count = int(get_com_member(sel_mgr, "GetSelectedObjectCount2", -1) or 0)
                count = raw_count
                for index in range(1, min(raw_count, SELECTION_ITEMS_LIMIT) + 1):
                    obj_type = "UNKNOWN"
                    try:
                        obj_type = str(get_com_member(sel_mgr, "GetSelectedObjectType3", index, -1) or "")
                    except Exception:
                        log.debug('COM 成员探测失败', exc_info=True)
                    component = ""
                    try:
                        comp = get_com_member(sel_mgr, "GetSelectedObjectsComponent4", index, -1)
                        if comp is not None:
                            component = str(get_com_member(comp, "Name2") or "")
                    except Exception:
                        log.debug('COM 成员探测失败', exc_info=True)
                    items.append({"index": index, "type": obj_type, "component": component})
            except Exception:
                log.debug('COM 成员探测失败', exc_info=True)
            info = {"doc_title": doc_title, "count": count, "items": items,
                    "_doc_identity": (doc_title, doc_path)}
        if info != self._selection_cache:
            # 活动文档切换（身份含路径）：旧文档的 Motion Study 等 COM 槽位全部失效
            new_identity = (info or {}).get("_doc_identity")
            if prev_identity is not None and info is not None and new_identity != prev_identity:
                self.last_motion_study = None
            self._selection_cache = info
            self._selection_info = info
            self._emit_update(label="selection_poll")

    # === 多文档 / 尺寸读取（线程内调用） ===

    def list_documents(self) -> list[dict[str, Any]]:
        """枚举 SolidWorks 中打开的全部文档（活动者标记 active）。"""
        from illusion_forge.cad.vendor.sw_connect import get_com_member

        active = self.active_model(required=False)
        active_title = ""
        if active is not None:
            try:
                active_title = str(get_com_member(active, "GetTitle") or "")
            except Exception:
                log.debug('COM 成员探测失败', exc_info=True)
        result: list[dict[str, Any]] = []
        docs = get_com_member(self.sw, "GetDocuments") or []
        for doc in docs:
            title, path, doc_type = "", "", 0
            try:
                title = str(get_com_member(doc, "GetTitle") or "")
            except Exception:
                log.debug('CAD 边界操作失败', exc_info=True)
            try:
                path = str(get_com_member(doc, "GetPathName") or "")
            except Exception:
                log.debug('CAD 边界操作失败', exc_info=True)
            try:
                doc_type = int(get_com_member(doc, "GetType") or 0)
            except Exception:
                log.debug('CAD 边界操作失败', exc_info=True)
            result.append({
                "title": title,
                "path": path,
                "doc_type": {1: "part", 2: "assembly", 3: "drawing"}.get(doc_type, str(doc_type)),
                "active": title == active_title,
            })
        return result

    def delete_feature(self, name: str) -> dict[str, Any]:
        """按名称删除特征（EditDelete；gcm 二态访问，失败抛错）。"""
        from illusion_forge.cad.vendor.sw_connect import get_com_member

        model = self.active_model()
        # 选中最可靠：SelectByID2 标记后走 EditDelete
        ok = get_com_member(model.Extension, "SelectByID2", name, "BODYFEATURE", 0, 0, 0, False, 0, None)
        if not ok:
            raise ValueError(f"未找到可删除的特征: {name}")
        get_com_member(model, "EditDelete")
        get_com_member(model, "ClearSelection2", True)
        return {"deleted": name}

    def read_dimensions_mm(self, names: list[str]) -> dict[str, Any]:
        """按名称读取命名尺寸（毫米；未命名的报 missing，不抛错）。"""
        from illusion_forge.cad.vendor.sw_connect import get_com_member

        model = self.active_model()
        values: dict[str, Any] = {}
        for name in names:
            try:
                param = get_com_member(model, "Parameter", name)
                meters = get_com_member(param, "SystemValue")
                values[name] = round(float(meters) * 1000.0, 6)
            except (AttributeError, TypeError, ValueError, com_error) as exc:
                values[name] = {"missing": True, "error": str(exc)}
        return values

    # === 可视化载荷 ===

    def feature_tree(self) -> list[dict[str, Any]]:
        """遍历当前文档特征树（线程内调用；超限截断）。"""
        from illusion_forge.cad.vendor.sw_connect import get_com_member

        model = self.active_model(required=False)
        if model is None:
            return []
        features: list[dict[str, Any]] = []
        try:
            feat = get_com_member(model, "FirstFeature")
            while feat is not None and len(features) < TREE_LIMIT:
                name: Any = ""
                type_name: Any = ""
                try:
                    name = get_com_member(feat, "Name")
                    type_name = get_com_member(feat, "GetTypeName2")
                except Exception:
                    log.debug('CAD 边界操作失败', exc_info=True)
                features.append({"name": str(name or ""), "type": str(type_name or "")})
                feat = get_com_member(feat, "GetNextFeature")
        except (AttributeError, TypeError, com_error) as exc:
            log.debug("特征树遍历中断: %s", exc)
        return features

    def document_info(self) -> dict[str, Any] | None:
        """活动文档信息（标题/路径/类型；线程内调用，结果写入跨线程缓存）。"""
        from illusion_forge.cad.vendor.sw_connect import get_com_member

        model = self.active_model(required=False)
        if model is None:
            self._last_document_info = None
            return None
        info: dict[str, Any] = {}
        for key, attr in (("title", "GetTitle"), ("path", "GetPathName"), ("type", "GetType")):
            try:
                info[key] = str(get_com_member(model, attr) or "")
            except Exception:
                log.debug('CAD 边界操作失败', exc_info=True)
        # doc type: 1=part 2=assembly 3=drawing
        type_map = {"1": "part", "2": "assembly", "3": "drawing"}
        info["doc_type"] = type_map.get(info.get("type", "").split(".")[0], info.get("type", ""))
        self._last_document_info = info
        return info

    def cached_document_info(self) -> dict[str, Any] | None:
        """返回最近一次线程内缓存的文档信息（其他线程安全读取，零 COM）。"""
        return self._last_document_info

    def _emit_update(self, label: str) -> None:
        """任务完成后构造可视化载荷广播（宿主线程内）。"""
        payload: dict[str, Any] = {
            "label": label,
            "state": self.state(),
            "document": self.document_info(),
            "tree": self.feature_tree(),
            "latest_frame": self.latest_snapshot(),
            "selection": self._selection_info,
        }
        try:
            broadcast_cad_update(payload)
        except Exception:
            log.exception("广播 cad_update 失败")
