"""CAD 画布工作台回归测试（M1-M4 会话内验证的固化）。

覆盖：CanvasStore 操作与契约、SolidWorksHost 线程机制（串行/超时/
异常/重启状态清理）、选中项轮询（文档身份 = title+path）、尺寸读取、
lineage 工具全流程、cad_routes 路径校验。

SolidWorks COM 用最小假对象模拟——不启动真实 SolidWorks。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from illusion_forge.cad.canvas_store import CanvasStore
from illusion_forge.cad.host import CadHostError, SolidWorksHost
from illusion_forge.cad.events import subscribe_cad_broadcast


# === 测试用假 COM 对象 ===


class FakeSelectionManager:
    def __init__(self, count: int) -> None:
        self.count = count

    def GetSelectedObjectCount2(self, mark: int = -1) -> int:
        return self.count

    def GetSelectedObjectType3(self, index: int, mark: int = -1) -> str:
        return "FACE"

    def GetSelectedObjectsComponent4(self, index: int, mark: int = -1) -> None:
        return None


class FakeModel:
    def __init__(self, title: str, path: str, dims: dict[str, float] | None = None) -> None:
        self._title = title
        self._path = path
        self._dims = dims or {}

    def GetTitle(self) -> str:
        return self._title

    def GetPathName(self) -> str:
        return self._path

    def GetType(self) -> int:
        return 1

    def SelectionManager(self) -> FakeSelectionManager:
        return FakeSelectionManager(2)

    def Parameter(self, name: str) -> Any:
        if name not in self._dims:
            # 真实 SolidWorks 对缺失尺寸抛 com_error（属性访问失败族）
            raise AttributeError(f"dimension not found: {name}")
        return _FakeParam(self._dims[name])


class _FakeParam:
    def __init__(self, meters: float) -> None:
        self._meters = meters

    def SystemValue(self) -> float:
        return self._meters


class FakeSw:
    def __init__(self, model: FakeModel) -> None:
        self._model = model

    @property
    def ActiveDoc(self) -> FakeModel:
        return self._model

    def GetDocuments(self) -> tuple:
        return (self._model,)


@pytest.fixture()
def host() -> SolidWorksHost:
    """独立宿主实例（绕过单例缓存，测试互不污染）。"""
    return SolidWorksHost()


def _reset_poll(host: SolidWorksHost) -> None:
    host._last_poll_at = 0.0


# === CanvasStore ===


class TestCanvasStore:
    def test_add_update_remove_and_persist(self, tmp_path: Path) -> None:
        CanvasStore._instances.pop(str(tmp_path).lower(), None)
        store = CanvasStore.for_cwd(tmp_path)
        snap = store.apply_op({"action": "add_node", "kind": "variant", "title": "方案A", "data": {"params": {"D1@Sketch1": 50.0}}})
        node_id = snap["nodes"][-1]["id"]
        snap = store.apply_op({"action": "update_node", "node_id": node_id, "body": "更新"})
        snap = store.apply_op({"action": "remove_node", "node_id": node_id})
        assert snap["nodes"] == []
        # 持久化重载
        assert CanvasStore.for_cwd(tmp_path).get_doc()["revision"] == snap["revision"]

    def test_replace_from_frontend_normalizes(self, tmp_path: Path) -> None:
        CanvasStore._instances.pop(str(tmp_path).lower(), None)
        store = CanvasStore.for_cwd(tmp_path)
        snap = store.apply_op({"action": "add_node", "kind": "requirement", "title": "需求"})
        node_id = snap["nodes"][-1]["id"]
        # 未知顶层字段被丢弃（严格契约），data 透传保留
        snap = store.replace_from_frontend({
            "nodes": [{"id": node_id, "kind": "variant", "title": "改", "position": {"x": 10, "y": 20},
                       "data": {"params": {"D1@Sketch1": 50.0}}, "rogue_field": 1}],
            "edges": [],
        })
        node = snap["nodes"][0]
        assert "rogue_field" not in node
        assert node["data"]["params"] == {"D1@Sketch1": 50.0}

    def test_invalid_op_raises(self, tmp_path: Path) -> None:
        CanvasStore._instances.pop(str(tmp_path).lower(), None)
        store = CanvasStore.for_cwd(tmp_path)
        with pytest.raises(ValueError, match="不支持的画布操作"):
            store.apply_op({"action": "nuke_everything"})
        with pytest.raises(ValueError, match="未知节点类型"):
            store.apply_op({"action": "add_node", "kind": "not_a_kind"})


# === SolidWorksHost 线程机制 ===


class TestHostMechanics:
    async def test_serial_execution(self, host: SolidWorksHost) -> None:
        order: list[str] = []

        async def slow() -> None:
            await host.run("slow", lambda h: (time.sleep(0.2), order.append("slow"))[1])

        async def quick() -> None:
            await asyncio.sleep(0.05)
            await host.run("quick", lambda h: order.append("quick"))

        await asyncio.gather(slow(), quick())
        assert order == ["slow", "quick"]

    async def test_timeout_raises_cad_busy_and_recovers(self, host: SolidWorksHost) -> None:
        with pytest.raises(CadHostError, match="cad_busy|等待") as exc_info:
            await host.run("hang", lambda h: time.sleep(1.0), timeout=0.2)
        assert exc_info.value.code == "cad_busy"
        await asyncio.sleep(1.2)  # 挂起任务结束（COM 不可强杀语义）
        assert await host.run("after", lambda h: "recovered") == "recovered"

    async def test_exception_forwarded(self, host: SolidWorksHost) -> None:
        with pytest.raises(ZeroDivisionError):
            await host.run("boom", lambda h: 1 / 0)

    async def test_thread_death_resets_com_state(self, host: SolidWorksHost) -> None:
        """线程死亡重启契约：COM 状态必须被清空（审查 Important#2 回归）。"""
        await host.run("warmup", lambda h: "ok")
        # 模拟线程死亡：置停并等待线程退出
        host._stop = True
        host._thread.join(timeout=3.0)
        assert not host._thread.is_alive()
        host._sw = object()  # 残留悬挂 COM 指针
        host.last_motion_study = object()
        await host.run("restart", lambda h: "ok")  # 触发 _ensure_thread 重启
        assert host._sw is None
        assert host.last_motion_study is None
        assert host._owned is False


# === 选中项轮询（文档身份 = title + path） ===


class TestSelectionPoll:
    async def test_poll_detects_selection(self, host: SolidWorksHost) -> None:
        events: list[str] = []
        unsub = subscribe_cad_broadcast(lambda p: events.append(p["label"]))
        host._sw = FakeSw(FakeModel("Part1", r"C:\t\Part1.SLDPRT"))
        try:
            _reset_poll(host)
            host._poll_selection()
            assert host.selection_info()["count"] == 2
            # 无变化不广播
            before = len(events)
            _reset_poll(host)
            host._poll_selection()
            assert len(events) == before
            # 同标题不同路径 = 文档切换 → 失效 Motion 槽位（审查 Important#1 回归）
            host.last_motion_study = object()
            host._sw = FakeSw(FakeModel("Part1", r"C:\t\OtherPart.SLDPRT"))
            _reset_poll(host)
            host._poll_selection()
            assert host.last_motion_study is None
            assert "selection_poll" in events
        finally:
            host._sw = None
            unsub()


# === 尺寸读取与 lineage 工具 ===


class TestDimensionAndLineage:
    async def test_read_dimensions(self, host: SolidWorksHost) -> None:
        host._sw = FakeSw(FakeModel("Part1", r"C:\t\Part1.SLDPRT", {"D1@Sketch1": 0.05}))
        values = host.read_dimensions_mm(["D1@Sketch1", "D9@Missing"])
        assert values["D1@Sketch1"] == 50.0
        assert values["D9@Missing"]["missing"] is True

    async def test_link_and_diff_flow(self, tmp_path: Path) -> None:
        from illusion_forge.cad.tools import CanvasAddNodeInput, create_cad_tools
        from illusion_forge.cad.tools.production import CadDimensionDiffInput, CadDocumentLinkInput

        CanvasStore._instances.pop(str(tmp_path).lower(), None)
        host = SolidWorksHost.instance()  # 工具经单例提交任务，必须注入单例
        # 先热身启动宿主线程（_ensure_thread 的重启契约会在启动时清 COM
        # 状态——生产中只有线程内的 connect() 会设置 _sw），再注入假对象
        await host.run("warmup", lambda h: "ok")
        host._sw = FakeSw(FakeModel("Part1", r"C:\t\Part1.SLDPRT", {"D1@Sketch1": 0.05, "D2@Sketch1": 0.025}))
        try:
            tools = {t.name: t for t in create_cad_tools()}
            context = type("Ctx", (), {"cwd": tmp_path, "metadata": {}, "on_progress": None})()

            added = await tools["canvas_add_node"].execute(
                CanvasAddNodeInput(kind="variant", title="方案A", data={"params": {"D1@Sketch1": 50.0, "D2@Sketch1": 30.0}}),
                context,
            )
            node_id = json_loads(added.output)["node_id"]
            linked = await tools["cad_document_link"].execute(CadDocumentLinkInput(node_id=node_id), context)
            assert json_loads(linked.output)["status"] == "ok"
            diff = await tools["cad_dimension_diff"].execute(CadDimensionDiffInput(node_id=node_id), context)
            payload = json_loads(diff.output)
            statuses = {row["dimension"]: row["status"] for row in payload["rows"]}
            assert statuses["D1@Sketch1"] == "match"
            assert statuses["D2@Sketch1"] == "mismatch"
            assert payload["summary"]["mismatch"] == 1
            node = next(n for n in CanvasStore.for_cwd(tmp_path).get_doc()["nodes"] if n["id"] == node_id)
            assert node["data"]["model_title"] == "Part1"
        finally:
            host._sw = None


def json_loads(text: str) -> Any:
    import json

    return json.loads(text)


# === cad_routes 路径校验 ===


class TestArtifactRouteValidation:
    def _get_endpoint(self):
        from illusion_forge.ui.web.server import create_app

        app = create_app()
        route = next(r for r in app.routes if getattr(r, "path", "") == "/api/cad/artifact")
        return route.endpoint

    def test_outside_path_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """artifacts 目录树外的文件必须被拒（含 symlink 场景：resolve 后落在树外）。"""
        import asyncio

        from fastapi import HTTPException

        endpoint = self._get_endpoint()
        secret = tmp_path / "secret.txt"
        secret.write_text("x", encoding="utf-8")
        with pytest.raises(HTTPException):
            asyncio.run(endpoint(path=str(secret)))
