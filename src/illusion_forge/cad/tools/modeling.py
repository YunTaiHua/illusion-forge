"""SolidWorks 建模工具域（M2：建模闭环）。

会话（连接/文档生命周期）+ 零件（草图/特征/孔/尺寸）+ 装配（组件/配合/
检查）+ 可视化（相机/快照/审查）+ 导出。全部经
``SolidWorksHost.instance().run()`` 在宿主 STA 线程内执行 vendored
sw_* 逻辑，工具侧只收发纯数据。

约定：
- 长度/距离参数一律毫米（工具内经 vendor 的 ``mm()`` 换算成米），
  角度一律度（``deg()`` 换算成弧度）；
- 建模类操作完成后自动抓取等轴测快照帧（``cad_update`` 事件实时推送，
  画布可选钉快照卡，形成分镜流）；
- 写操作默认走权限确认（is_read_only=False），只读类检查/快照免确认。
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator

from illusion_forge.cad.host import (
    CONNECT_TIMEOUT,
    DEFAULT_OP_TIMEOUT,
    CadHostError,
    SolidWorksHost,
)
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult


def _json_result(payload: Any, is_error: bool = False) -> ToolResult:
    return ToolResult(output=json.dumps(payload, ensure_ascii=False, default=str), is_error=is_error)


def _error_result(exc: Exception, label: str) -> ToolResult:
    if isinstance(exc, CadHostError):
        return _json_result({"status": "failed", "error_code": exc.code, "error": str(exc)}, is_error=True)
    return _json_result({"status": "failed", "error_code": "cad_op_failed", "error": f"{label}: {exc}"}, is_error=True)


async def _submit(
    context: ToolExecutionContext,
    label: str,
    fn: Callable[[SolidWorksHost], dict[str, Any]],
    *,
    timeout: float = DEFAULT_OP_TIMEOUT,
    snapshot: bool = True,
    snapshot_views: tuple[str, ...] = ("isometric",),
    pin: bool = False,
    connect_to: list[str] | None = None,
    card_title: str | None = None,
) -> ToolResult:
    """提交宿主任务；成功后抓快照帧并按需钉快照卡。

    Args:
        fn: 在宿主线程执行的闭包（返回结果 dict，会在其中注入 frames）
        snapshot: 是否在操作后抓取等轴测快照（可视化/分镜数据源）
        pin: 是否把快照卡钉到画布（feature 类操作 True → 分镜）
    """
    from illusion_forge.cad.canvas_store import CanvasStore, artifacts_root

    artifacts_dir = artifacts_root(context.cwd)

    def job(host: SolidWorksHost) -> dict[str, Any]:
        result = fn(host) or {}
        result.setdefault("frames", [])
        if snapshot:
            try:
                result["frames"] = host.capture_snapshot(artifacts_dir, label, views=snapshot_views)
            except Exception as exc:  # noqa: BLE001 — 快照失败降级不阻塞建模  # 快照失败不阻塞建模操作
                result.setdefault("limitations", []).append(f"快照抓取失败: {exc}")
        return result

    try:
        result = await SolidWorksHost.instance().run(label, job, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — 宿主/COM 异常统一转结构化错误码
        return _error_result(exc, label)

    if pin and result.get("frames"):
        entry = result["frames"][0]
        try:
            snapshot_doc = CanvasStore.for_session(
                context.cwd, context.metadata.get("session_id", "")
            ).apply_op({
                "action": "add_node",
                "kind": "snapshot",
                "title": card_title or label,
                "body": "",
                "data": {"image_path": entry["path"], "view": entry["view"]},
                "connect_to": connect_to or [],
            })
            result["canvas_node_id"] = snapshot_doc["nodes"][-1]["id"]
        except ValueError as exc:
            result.setdefault("limitations", []).append(f"快照卡钉画布失败: {exc}")
    return _json_result(result)


# === 会话工具 ===


class CadConnectInput(BaseModel):
    """连接参数。"""

    version: str | None = Field(default=None, description="自动选择（默认，留空）。仅当用户明确指定年份且默认版本不对时才传年份（如 2022，数字或字符串均可，内部自动归一化）；版本 ProgID 未注册时自动回退到本机最新版本")
    visible: bool = Field(default=True, description="是否显示 SolidWorks 窗口（建议 True，用户可实时观看建模）")

    @field_validator("version", mode="before")
    @classmethod
    def _normalize_version(cls, value: Any) -> Any:
        """宽容解析版本：int/float 年份转字符串，"auto"/空串归一为自动选择。"""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return str(int(value))
        if isinstance(value, str):
            text = value.strip()
            return None if text.lower() in ("", "auto", "automatic", "default", "null") else text
        return value


class CadConnectTool(BaseTool[CadConnectInput]):
    """连接 SolidWorks（附着已运行实例优先，否则启动新实例）。"""

    name = "cad_connect"
    description = """Attach to a running SolidWorks instance (preferred) or launch a new one, and hold a process-wide session for subsequent cad_* tools.

Version defaults to AUTO-SELECT: omit `version` entirely (do not guess a year). Only pass a year (e.g. 2022, number or string) when the user explicitly names one AND auto-select picked the wrong release. Unregistered version ProgIDs fall back to the newest installed release.

Call cad_health_check first to learn what is installed. Connection can take a while on cold start (license validation). All later cad_* tools share this single session; the session survives agent restarts as long as SolidWorks keeps running."""
    input_model = CadConnectInput

    async def execute(self, arguments: CadConnectInput, context: ToolExecutionContext) -> ToolResult:
        version = arguments.version
        if version and not version.isdigit():
            return _json_result({"status": "failed", "error": 'version 需为年份（如 "2022"）或 null'}, is_error=True)
        from illusion_forge.cad.host import SolidWorksHost as _Host

        def job(host: _Host) -> dict[str, Any]:
            metadata = host.connect(version=version or None, visible=arguments.visible)
            return {"status": "ok", "metadata": metadata, "state": host.state(), "document": host.document_info()}

        return await _submit(context, "cad_connect", job, timeout=CONNECT_TIMEOUT, snapshot=False)


class CadSessionStatusInput(BaseModel):
    """会话状态无参数。"""


class CadSessionStatusTool(BaseTool[CadSessionStatusInput]):
    """查询会话状态、活动文档与特征树。"""

    name = "cad_session_status"
    description = """Report the SolidWorks session state (connected/busy/owned), active document info (title/path/type), the full feature tree, and recent snapshot frames. Read-only; use it to re-orient after user edits or before planning the next operation."""
    input_model = CadSessionStatusInput

    def is_read_only(self, arguments: CadSessionStatusInput) -> bool:
        return True

    async def execute(self, arguments: CadSessionStatusInput, context: ToolExecutionContext) -> ToolResult:
        del arguments

        def job(host: SolidWorksHost) -> dict[str, Any]:
            host.modules()  # 未连接时给出明确错误
            return {
                "status": "ok",
                "state": host.state(),
                "document": host.document_info(),
                "tree": host.feature_tree(),
                "recent_snapshots": host.snapshot_history()[:10],
            }

        return await _submit(context, "cad_session_status", job, snapshot=False)


class CadNewDocumentInput(BaseModel):
    """新建文档参数。"""

    doc_type: Literal["part", "assembly", "drawing"] = Field(description="文档类型")
    template_path: str | None = Field(default=None, description="模板路径（缺省用系统默认模板）")


class CadNewDocumentTool(BaseTool[CadNewDocumentInput]):
    """在 SolidWorks 中新建零件/装配体/工程图。"""

    name = "cad_new_document"
    description = """Create a new part/assembly/drawing document in the connected SolidWorks session. Requires cad_connect first. Returns the new document title; subsequent sketch/feature tools operate on it."""
    input_model = CadNewDocumentInput

    async def execute(self, arguments: CadNewDocumentInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            connect = host.modules()["connect"]
            model = connect.new_document(host.sw, doc_type=arguments.doc_type, template_path=arguments.template_path)
            title = str(connect.get_com_member(model, "GetTitle") or "") if model is not None else ""
            return {"status": "ok", "created": title}

        return await _submit(context, "cad_new_document", job, pin=False)


class CadOpenDocumentInput(BaseModel):
    """打开文档参数。"""

    path: str = Field(description="文档绝对路径（.sldprt/.sldasm/.slddrw；也可打开 STEP/IGES 等外来格式）")
    read_only: bool = Field(default=False, description="是否只读打开")


class CadOpenDocumentTool(BaseTool[CadOpenDocumentInput]):
    """打开已有文档（含 STEP/IGES 等中性格式导入）。"""

    name = "cad_open_document"
    description = """Open an existing document (.sldprt/.sldasm/.slddrw) or import a neutral format (STEP/IGES) into SolidWorks. Requires cad_connect first."""
    input_model = CadOpenDocumentInput

    async def execute(self, arguments: CadOpenDocumentInput, context: ToolExecutionContext) -> ToolResult:
        path = arguments.path
        if not Path(path).is_file():
            return _json_result({"status": "failed", "error": f"文件不存在: {path}"}, is_error=True)

        def job(host: SolidWorksHost) -> dict[str, Any]:
            connect = host.modules()["connect"]
            model = connect.open_document(host.sw, path, read_only=arguments.read_only, silent=True, raise_on_error=True)
            title = str(connect.get_com_member(model, "GetTitle") or "") if model is not None else ""
            return {"status": "ok", "opened": title}

        return await _submit(context, "cad_open_document", job)


class CadSaveDocumentInput(BaseModel):
    """保存参数。"""

    path: str | None = Field(default=None, description="另存为路径；缺省保存到当前路径")


class CadSaveDocumentTool(BaseTool[CadSaveDocumentInput]):
    """保存/另存为活动文档。"""

    name = "cad_save_document"
    description = """Save (or Save As when path given) the active document. Prompts for confirmation by design — overwriting user files requires consent."""
    input_model = CadSaveDocumentInput

    async def execute(self, arguments: CadSaveDocumentInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            connect = host.modules()["connect"]
            ok = connect.save_document(host.active_model(), file_path=arguments.path)
            return {"status": "ok" if ok else "unknown", "saved": bool(ok)}

        return await _submit(context, "cad_save_document", job, snapshot=False)


class CadCloseDocumentsInput(BaseModel):
    """关闭文档参数。"""

    quit_solidworks: bool = Field(default=False, description="是否同时退出 SolidWorks（仅限由 cad_connect 启动的实例）")


class CadCloseDocumentsTool(BaseTool[CadCloseDocumentsInput]):
    """关闭所有文档（可选退出 SolidWorks）。"""

    name = "cad_close_documents"
    description = """Close all open documents in the session; optionally quit SolidWorks entirely (only allowed when the instance was launched by cad_connect, not when attached to the user's own session). Unsaved changes may prompt dialogs inside SolidWorks."""
    input_model = CadCloseDocumentsInput

    async def execute(self, arguments: CadCloseDocumentsInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            sw = host.sw
            try:
                sw.CloseAllDocuments(True)
            except Exception as exc:
                raise CadHostError(f"关闭文档失败: {exc}", "cad_close_failed") from exc
            quit_done = False
            if arguments.quit_solidworks:
                quit_done = host.quit_owned()
                if not quit_done:
                    raise CadHostError("该实例由用户自行启动，不能远程退出；请手动关闭。", "cad_not_owned")
            return {"status": "ok", "quit": quit_done}

        return await _submit(context, "cad_close_documents", job, snapshot=False)


# === 零件工具 ===


class SketchPrimitive(BaseModel):
    """单个草图原语（坐标单位毫米；需与 type 匹配的参数）。

    Attributes:
        type: line / rectangle（中心+宽高）/ corner_rectangle（两角点）/
            circle（圆心+半径）/ arc（圆心+起点+终点）/ polygon（圆心+外接半径+边数）/
            slot（两端点+半径）/ spline（点列）；兼容 kind 作为字段别名
        cx, cy: 圆心/中心 X、Y
        x1, y1, x2, y2: 端点或角点坐标
        radius: 半径
        w, h: 矩形宽高
        sides: 多边形边数
        direction: 圆弧方向（1 逆时针 / -1 顺时针）
        points: 样条点列 [[x, y], ...]
    """

    model_config = {"populate_by_name": True}

    type: Literal["line", "rectangle", "corner_rectangle", "circle", "arc", "polygon", "slot", "spline"] = Field(
        validation_alias=AliasChoices("type", "kind"),
    )
    cx: float | None = None
    cy: float | None = None
    x1: float | None = None
    y1: float | None = None
    x2: float | None = None
    y2: float | None = None
    radius: float | None = None
    w: float | None = None
    h: float | None = None
    sides: int = Field(default=6, ge=3, le=64)
    direction: int = Field(default=1, ge=-1, le=1)
    points: list[list[float]] | None = None


class CadSketchAddInput(BaseModel):
    """加草图参数：在指定基准面上新建草图并绘制多个原语。"""

    plane_name: str = Field(default="Front Plane", description='基准面名（"Front Plane"/"Top Plane"/"Right Plane"，中英文别名均可）')
    primitives: list[SketchPrimitive] = Field(min_length=1, description="草图原语列表（一次调用 = 一个草图）")


class CadSketchAddTool(BaseTool[CadSketchAddInput]):
    """新建草图并绘制原语（一次调用生成一个完整草图）。"""

    name = "cad_sketch_add"
    description = """Start a new sketch on a plane and draw primitives inside it (one call = one closed sketch). Units are millimeters.

Each primitive object MUST carry a discriminator field `type` (alias `kind` is also accepted): e.g. {"type":"circle","cx":0,"cy":0,"radius":25}, {"type":"rectangle","cx":10,"cy":20,"w":50,"h":30}. Available primitives: circle(cx,cy,radius), rectangle(cx,cy,w,h), corner_rectangle(x1,y1,x2,y2), line(x1,y1,x2,y2), arc(cx,cy,x1,y1,x2,y2,direction), polygon(cx,cy,radius,sides), slot(x1,y1,x2,y2,radius), spline(points).

Typical flow: cad_new_document(part) → cad_sketch_add(circle r=25 on Front Plane) → cad_feature_extrude(depth 50). Returns the sketch name to feed into feature tools."""
    input_model = CadSketchAddInput

    async def execute(self, arguments: CadSketchAddInput, context: ToolExecutionContext) -> ToolResult:
        primitives = [p.model_dump() for p in arguments.primitives]

        # 进入 COM 前一次性校验全部原语参数（避免草图画到一半才失败留下半成品）
        _REQUIRED: dict[str, tuple[str, ...]] = {
            "line": ("x1", "y1", "x2", "y2"),
            "rectangle": ("cx", "cy", "w", "h"),
            "corner_rectangle": ("x1", "y1", "x2", "y2"),
            "circle": ("cx", "cy", "radius"),
            "arc": ("cx", "cy", "x1", "y1", "x2", "y2"),
            "polygon": ("cx", "cy", "radius"),
            "slot": ("x1", "y1", "x2", "y2", "radius"),
            "spline": ("points",),
        }
        missing_report = []
        for index, prim in enumerate(primitives):
            kind = prim["type"]
            for key in _REQUIRED[kind]:
                value = prim.get(key)
                if value is None or (key == "points" and not value):
                    missing_report.append(
                        f"primitives[{index}]({kind}) 缺少 {key}；"
                        f"{kind} 需要参数: {', '.join(_REQUIRED[kind])}"
                    )
        if missing_report:
            raise ValueError("草图原语参数不完整: " + "; ".join(missing_report))

        def job(host: SolidWorksHost) -> dict[str, Any]:
            part = host.modules()["part"]
            connect = host.modules()["connect"]
            model = host.active_model()
            mm = connect.mm

            def _v(prim: dict[str, Any], key: str) -> float:
                value = prim.get(key)
                if value is None:
                    raise ValueError(f"原语 {prim['type']} 缺少参数 {key}")
                return float(mm(float(value)))

            with part.sketch(model, arguments.plane_name) as sketch_name:
                for prim in primitives:
                    kind = prim["type"]
                    if kind == "circle":
                        part.sketch_circle(model, _v(prim, "cx"), _v(prim, "cy"), _v(prim, "radius"))
                    elif kind == "rectangle":
                        part.sketch_rectangle(model, _v(prim, "cx"), _v(prim, "cy"), _v(prim, "w"), _v(prim, "h"))
                    elif kind == "corner_rectangle":
                        part.sketch_corner_rectangle(model, _v(prim, "x1"), _v(prim, "y1"), _v(prim, "x2"), _v(prim, "y2"))
                    elif kind == "line":
                        part.sketch_line(model, _v(prim, "x1"), _v(prim, "y1"), _v(prim, "x2"), _v(prim, "y2"))
                    elif kind == "arc":
                        part.sketch_arc(model, _v(prim, "cx"), _v(prim, "cy"), _v(prim, "x1"), _v(prim, "y1"),
                                        _v(prim, "x2"), _v(prim, "y2"), int(prim["direction"]))
                    elif kind == "polygon":
                        part.sketch_polygon(model, _v(prim, "cx"), _v(prim, "cy"), _v(prim, "radius"), int(prim["sides"]))
                    elif kind == "slot":
                        part.sketch_slot(model, _v(prim, "x1"), _v(prim, "y1"), _v(prim, "x2"), _v(prim, "y2"), _v(prim, "radius"))
                    elif kind == "spline":
                        points = prim.get("points") or []
                        if len(points) < 2:
                            raise ValueError("spline 至少需要 2 个点")
                        part.sketch_spline(model, [(mm(float(px)), mm(float(py))) for px, py in points])
            return {"status": "ok", "sketch_name": sketch_name, "primitive_count": len(primitives)}

        return await _submit(context, "cad_sketch_add", job)


class CadFeatureExtrudeInput(BaseModel):
    """拉伸参数。"""

    sketch_name: str = Field(description="要拉伸的草图名（cad_sketch_add 返回值）")
    operation: Literal["boss", "cut", "midplane"] = Field(description="boss=凸台 / cut=切除 / midplane=两侧对称凸台")
    depth_mm: float = Field(gt=0, description="深度（毫米；midplane 为总深度）")
    flip: bool = Field(default=False, description="cut 时是否反向切除")
    merge: bool = Field(default=True, description="是否与既有实体合并")


class CadFeatureExtrudeTool(BaseTool[CadFeatureExtrudeInput]):
    """拉伸已草图：凸台 / 切除 / 中面对称。"""

    name = "cad_feature_extrude"
    description = """Extrude an existing sketch: "boss" adds material, "cut" removes material, "midplane" extrudes symmetrically about the sketch plane. Depth in millimeters."""
    input_model = CadFeatureExtrudeInput

    async def execute(self, arguments: CadFeatureExtrudeInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            part = host.modules()["part"]
            connect = host.modules()["connect"]
            model = host.active_model()
            depth = connect.mm(arguments.depth_mm)
            if arguments.operation == "boss":
                feature = part.extrude_boss(model, arguments.sketch_name, depth, merge=arguments.merge)
            elif arguments.operation == "cut":
                feature = part.extrude_cut(model, arguments.sketch_name, depth, flip=arguments.flip)
            else:
                feature = part.extrude_midplane(model, arguments.sketch_name, depth)
            return {"status": "ok", "operation": arguments.operation, "depth_mm": arguments.depth_mm,
                    "feature": str(feature) if feature is not None else None}

        return await _submit(context, "cad_feature_extrude", job, pin=True,
                             card_title=f"拉伸 {arguments.operation} {arguments.depth_mm}mm")


class CadFeatureRevolveInput(BaseModel):
    """旋转参数。"""

    sketch_name: str = Field(description="含闭合轮廓与（可选）中心线的草图名")
    angle_deg: float = Field(default=360.0, gt=0, le=360, description="旋转角度（度）")
    axis_sketch_name: str | None = Field(default=None, description="轴所在草图名（缺省用草图内中心线）")


class CadFeatureRevolveTool(BaseTool[CadFeatureRevolveInput]):
    """绕轴旋转草图生成旋转特征。"""

    name = "cad_feature_revolve"
    description = """Revolve a closed sketch around an axis (centerline in the sketch, or a separate axis sketch). Angle in degrees (360 for full revolve). Sketch must contain a closed profile and an axis line."""
    input_model = CadFeatureRevolveInput

    async def execute(self, arguments: CadFeatureRevolveInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            part = host.modules()["part"]
            connect = host.modules()["connect"]
            model = host.active_model()
            feature = part.revolve_boss(model, arguments.sketch_name, connect.deg(arguments.angle_deg),
                                        arguments.axis_sketch_name)
            return {"status": "ok", "angle_deg": arguments.angle_deg,
                    "feature": str(feature) if feature is not None else None}

        return await _submit(context, "cad_feature_revolve", job, pin=True,
                             card_title=f"旋转 {arguments.angle_deg}°")


class CadFeatureFilletInput(BaseModel):
    """圆角参数。"""

    radius_mm: float = Field(gt=0, description="圆角半径（毫米）")
    edges: list[str] | None = Field(default=None, description="边名称列表；缺省用当前选择集")


class CadFeatureFilletTool(BaseTool[CadFeatureFilletInput]):
    """对边加圆角。"""

    name = "cad_feature_fillet"
    description = """Apply a fillet (radius in mm) to named edges (e.g. ["Edge1@Boss-Extrude1"]) or to the current user selection when edges omitted."""
    input_model = CadFeatureFilletInput

    async def execute(self, arguments: CadFeatureFilletInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            part = host.modules()["part"]
            connect = host.modules()["connect"]
            model = host.active_model()
            feature = part.fillet(model, connect.mm(arguments.radius_mm), arguments.edges)
            return {"status": "ok", "radius_mm": arguments.radius_mm,
                    "feature": str(feature) if feature is not None else None}

        return await _submit(context, "cad_feature_fillet", job, pin=True,
                             card_title=f"圆角 R{arguments.radius_mm}")


class CadFeatureChamferInput(BaseModel):
    """倒角参数。"""

    distance_mm: float = Field(gt=0, description="倒角距离（毫米）")
    angle_deg: float = Field(default=45.0, gt=0, lt=180, description="倒角角度")


class CadFeatureChamferTool(BaseTool[CadFeatureChamferInput]):
    """对当前选择的边加倒角。"""

    name = "cad_feature_chamfer"
    description = """Apply a chamfer (distance in mm + angle) to the currently selected edges — select edges in SolidWorks (or via user) before calling, since selection-based chamfer is the supported path."""
    input_model = CadFeatureChamferInput

    async def execute(self, arguments: CadFeatureChamferInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            part = host.modules()["part"]
            connect = host.modules()["connect"]
            model = host.active_model()
            feature = part.chamfer(model, connect.mm(arguments.distance_mm), arguments.angle_deg)
            return {"status": "ok", "distance_mm": arguments.distance_mm,
                    "feature": str(feature) if feature is not None else None}

        return await _submit(context, "cad_feature_chamfer", job, pin=True,
                             card_title=f"倒角 {arguments.distance_mm}mm")


class CadFeaturePatternInput(BaseModel):
    """阵列参数。"""

    kind: Literal["linear", "circular"] = Field(
        validation_alias=AliasChoices("kind", "type"),
        description="阵列类型（字段名 kind，兼容 type）：linear=线性阵列 / circular=圆周阵列",
    )
    feature_name: str = Field(description="要阵列的特征名")
    direction: list[float] | None = Field(default=None, description="linear：方向向量 [x,y,z]（草图坐标系）")
    spacing_mm: float | None = Field(default=None, description="linear：实例间距（毫米）")
    count: int = Field(default=2, ge=2, le=1000, description="实例总数（含原始特征）")
    second_direction: list[float] | None = Field(default=None, description="linear：第二方向向量（可选）")
    second_spacing_mm: float | None = Field(default=None, description="linear：第二方向间距（毫米）")
    second_count: int | None = Field(default=None, description="linear：第二方向实例数（可选）")
    axis_name: str | None = Field(default=None, description="circular：旋转轴名（基准轴/临时轴）")
    angle_deg: float = Field(default=360.0, description="circular：总角度（度）")


class CadFeaturePatternTool(BaseTool[CadFeaturePatternInput]):
    """线性/圆周阵列既有特征。"""

    name = "cad_feature_pattern"
    description = """Pattern an existing feature. linear: give direction vector [x,y,z] (sketch coords, unitless), spacing_mm and count; optional second direction. circular: give axis_name (datum/temporary axis), angle_deg (total sweep) and count."""
    input_model = CadFeaturePatternInput

    async def execute(self, arguments: CadFeaturePatternInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            part = host.modules()["part"]
            connect = host.modules()["connect"]
            model = host.active_model()
            if arguments.kind == "linear":
                if not arguments.direction or arguments.spacing_mm is None:
                    raise ValueError("linear 阵列需要 direction 与 spacing_mm")
                dx, dy, dz = arguments.direction
                d2 = arguments.second_direction or [0.0, 0.0, 0.0]
                d2_spacing = connect.mm(arguments.second_spacing_mm) if arguments.second_spacing_mm else 0.0
                d2_count = arguments.second_count or 1
                feature = part.linear_pattern(
                    model, arguments.feature_name,
                    float(dx), float(dy), float(dz), connect.mm(arguments.spacing_mm), arguments.count,
                    d2_x=float(d2[0]), d2_y=float(d2[1]), d2_z=float(d2[2]),
                    d2_spacing=d2_spacing, d2_count=d2_count,
                )
            else:
                if not arguments.axis_name:
                    raise ValueError("circular 阵列需要 axis_name")
                feature = part.circular_pattern(model, arguments.feature_name, arguments.axis_name,
                                                connect.deg(arguments.angle_deg), arguments.count)
            return {"status": "ok", "kind": arguments.kind, "count": arguments.count,
                    "feature": str(feature) if feature is not None else None}

        return await _submit(context, "cad_feature_pattern", job, pin=True,
                             card_title=f"{arguments.kind} 阵列 ×{arguments.count}")


class CadFeatureShellInput(BaseModel):
    """抽壳参数。"""

    thickness_mm: float = Field(gt=0, description="壁厚（毫米）")
    faces_to_remove: list[str] | None = Field(default=None, description="要移除的面名列表；缺省用当前选择集")


class CadFeatureShellTool(BaseTool[CadFeatureShellInput]):
    """抽壳（可选移除指定面形成开口）。"""

    name = "cad_feature_shell"
    description = """Hollow the solid to a wall thickness (mm); optionally remove named faces to create openings (e.g. ["Face1<1>@Boss-Extrude1"]) or use current selection when omitted."""
    input_model = CadFeatureShellInput

    async def execute(self, arguments: CadFeatureShellInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            part = host.modules()["part"]
            connect = host.modules()["connect"]
            model = host.active_model()
            feature = part.shell(model, connect.mm(arguments.thickness_mm), arguments.faces_to_remove)
            return {"status": "ok", "thickness_mm": arguments.thickness_mm,
                    "feature": str(feature) if feature is not None else None}

        return await _submit(context, "cad_feature_shell", job, pin=True,
                             card_title=f"抽壳 {arguments.thickness_mm}mm")


class CadFeatureMirrorInput(BaseModel):
    """镜像参数。"""

    feature_name: str = Field(description="要镜像的特征名")
    mirror_plane_name: str = Field(description="镜像基准面名（如 Right Plane）")


class CadFeatureMirrorTool(BaseTool[CadFeatureMirrorInput]):
    """把既有特征镜像到基准面另一侧。"""

    name = "cad_feature_mirror"
    description = """Mirror an existing feature across a datum plane (e.g. mirror a cut across "Right Plane")."""
    input_model = CadFeatureMirrorInput

    async def execute(self, arguments: CadFeatureMirrorInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            part = host.modules()["part"]
            model = host.active_model()
            feature = part.mirror_feature(model, arguments.feature_name, arguments.mirror_plane_name)
            return {"status": "ok", "feature": str(feature) if feature is not None else None}

        return await _submit(context, "cad_feature_mirror", job, pin=True,
                             card_title=f"镜像 {arguments.feature_name}")


class CadFeatureRibInput(BaseModel):
    """筋参数。"""

    sketch_name: str = Field(description="筋轮廓草图名（开放轮廓）")
    thickness_mm: float = Field(gt=0, description="厚度（毫米）")


class CadFeatureRibTool(BaseTool[CadFeatureRibInput]):
    """用开放轮廓草图生成加强筋。"""

    name = "cad_feature_rib"
    description = """Create a rib from an open-profile sketch with given thickness (mm)."""
    input_model = CadFeatureRibInput

    async def execute(self, arguments: CadFeatureRibInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            part = host.modules()["part"]
            connect = host.modules()["connect"]
            model = host.active_model()
            feature = part.rib(model, arguments.sketch_name, connect.mm(arguments.thickness_mm))
            return {"status": "ok", "feature": str(feature) if feature is not None else None}

        return await _submit(context, "cad_feature_rib", job, pin=True,
                             card_title=f"筋 {arguments.thickness_mm}mm")


class CadHoleCreateInput(BaseModel):
    """孔特征参数。"""

    kind: Literal["blind", "through", "counterbore", "countersink"] = Field(
        validation_alias=AliasChoices("kind", "type"),
        description="孔类型（字段名 kind，兼容 type）",
    )
    plane_name: str = Field(default="Front Plane", description="孔所在基准面（孔轴垂直该面）")
    center: list[float] = Field(min_length=2, max_length=2, description="孔心 [x, y]（毫米，基准面坐标系）")
    diameter_mm: float = Field(gt=0, description="孔径（毫米）")
    depth_mm: float | None = Field(default=None, description="blind：孔深（毫米）")
    counterbore_diameter_mm: float | None = Field(default=None, description="counterbore：沉孔直径")
    counterbore_depth_mm: float | None = Field(default=None, description="counterbore：沉孔深度")
    countersink_diameter_mm: float | None = Field(default=None, description="countersink：锥口直径")
    countersink_angle_deg: float = Field(default=90.0, description="countersink：锥面包含角（度）")
    name: str | None = Field(default=None, description="特征名")


class CadHoleCreateTool(BaseTool[CadHoleCreateInput]):
    """创建各类孔特征（盲孔/通孔/沉孔/沉头孔）。"""

    name = "cad_hole_create"
    description = """Create a hole: blind (needs depth_mm), through, counterbore (needs counterbore_diameter_mm + counterbore_depth_mm) or countersink (needs countersink_diameter_mm; included angle default 90°). center is [x,y] in mm on the given plane; the hole axis is normal to that plane. All sizes in millimeters."""
    input_model = CadHoleCreateInput

    async def execute(self, arguments: CadHoleCreateInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            hole = host.modules()["hole"]
            connect = host.modules()["connect"]
            model = host.active_model()
            mm = connect.mm
            center = (mm(arguments.center[0]), mm(arguments.center[1]))
            diameter = mm(arguments.diameter_mm)
            name = arguments.name or None
            if arguments.kind == "blind":
                if arguments.depth_mm is None:
                    raise ValueError("blind 孔需要 depth_mm")
                evidence = hole.create_blind_hole(model, center, diameter, mm(arguments.depth_mm),
                                                  plane_name=arguments.plane_name, name=name or "盲孔")
            elif arguments.kind == "through":
                evidence = hole.create_through_hole(model, center, diameter,
                                                    plane_name=arguments.plane_name, name=name or "通孔")
            elif arguments.kind == "counterbore":
                if arguments.counterbore_diameter_mm is None or arguments.counterbore_depth_mm is None:
                    raise ValueError("counterbore 需要 counterbore_diameter_mm 与 counterbore_depth_mm")
                if arguments.counterbore_diameter_mm <= arguments.diameter_mm:
                    raise ValueError("counterbore_diameter_mm 必须大于 diameter_mm")
                evidence = hole.create_counterbore_hole(model, center, diameter,
                                                        mm(arguments.counterbore_diameter_mm),
                                                        mm(arguments.counterbore_depth_mm),
                                                        plane_name=arguments.plane_name, name=name or "沉孔")
            else:
                if arguments.countersink_diameter_mm is None:
                    raise ValueError("countersink 需要 countersink_diameter_mm")
                if arguments.countersink_diameter_mm <= arguments.diameter_mm:
                    raise ValueError("countersink_diameter_mm 必须大于 diameter_mm")
                evidence = hole.create_countersink_hole(model, center, diameter,
                                                        mm(arguments.countersink_diameter_mm),
                                                        arguments.countersink_angle_deg,
                                                        plane_name=arguments.plane_name, name=name or "沉头孔")
            return {"status": "ok", "kind": arguments.kind, "evidence": evidence}

        return await _submit(context, "cad_hole_create", job, pin=True,
                             card_title=f"{arguments.kind} 孔 Ø{arguments.diameter_mm}")


class CadDimensionUpdateInput(BaseModel):
    """尺寸修改参数。"""

    dimension_name: str = Field(description="命名尺寸名（如 \"D1@Sketch1\"）")
    value_mm: float = Field(description="新值（毫米）")
    rebuild: bool = Field(default=True, description="修改后是否立即 rebuild")
    save: bool = Field(default=False, description="修改后是否保存文档")


class CadDimensionUpdateTool(BaseTool[CadDimensionUpdateInput]):
    """按名称修改尺寸并触发重建（参数化驱动的核心手段）。"""

    name = "cad_dimension_update"
    description = """Change a named dimension (e.g. "D1@Sketch1") to a new value in millimeters and rebuild. This is THE parametric edit path for iterating on a design after review feedback. Returns audit evidence including old/new values."""
    input_model = CadDimensionUpdateInput

    async def execute(self, arguments: CadDimensionUpdateInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            docdata = host.modules()["docdata"]
            model = host.active_model()
            evidence = docdata.update_dimension_mm(model, arguments.dimension_name, arguments.value_mm,
                                                   rebuild=arguments.rebuild, save=arguments.save)
            return {"status": "ok", "evidence": evidence}

        return await _submit(context, "cad_dimension_update", job, pin=True,
                             card_title=f"{arguments.dimension_name} → {arguments.value_mm}mm")


# === 装配工具 ===


class CadComponentAddInput(BaseModel):
    """添加组件参数。"""

    part_path: str = Field(description="零件/子装配文件绝对路径")
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    config_name: str = Field(default="", description="配置名（空 = 当前配置）")


class CadComponentAddTool(BaseTool[CadComponentAddInput]):
    """向装配体插入组件（插入点单位毫米）。"""

    name = "cad_component_add"
    description = """Insert a part/sub-assembly file into the active assembly at [x,y,z] in millimeters (assembly origin coords). Requires an assembly document. Internal fallbacks (AddComponent5→4→open-first) are handled by the vendored layer."""
    input_model = CadComponentAddInput

    async def execute(self, arguments: CadComponentAddInput, context: ToolExecutionContext) -> ToolResult:
        if not Path(arguments.part_path).is_file():
            return _json_result({"status": "failed", "error": f"文件不存在: {arguments.part_path}"}, is_error=True)

        def job(host: SolidWorksHost) -> dict[str, Any]:
            assembly = host.modules()["assembly"]
            connect = host.modules()["connect"]
            model = host.active_model()
            component = assembly.add_component(model, arguments.part_path,
                                               connect.mm(arguments.x), connect.mm(arguments.y), connect.mm(arguments.z),
                                               config_name=arguments.config_name, sw=host.sw)
            name = str(assembly.safe_get_com_member(component, "Name2") or "") if component is not None else ""
            return {"status": "ok", "component": name}

        return await _submit(context, "cad_component_add", job, pin=True,
                             card_title=f"组件 {Path(arguments.part_path).name}")


class CadMateAddInput(BaseModel):
    """添加配合参数。"""

    kind: Literal["coincident", "distance"] = Field(
        validation_alias=AliasChoices("kind", "type"),
        description="配合类型（字段名 kind，兼容 type）：coincident=重合 / distance=距离",
    )
    entity1_name: str = Field(description="实体 1 名称（如 \"Face1<1>@Part1-1\"、\"Edge2@Sketch1\"）")
    entity1_type: str = Field(default="FACE", description='实体 1 类型（"FACE"/"EDGE"/"VERTEX"/"PLANE" 等 SelectByID2 类型名）')
    entity2_name: str = Field(description="实体 2 名称")
    entity2_type: str = Field(default="FACE", description="实体 2 类型")
    distance_mm: float | None = Field(default=None, description="distance：间距（毫米）")


class CadMateAddTool(BaseTool[CadMateAddInput]):
    """在装配体组件之间添加重合/距离配合。"""

    name = "cad_mate_add"
    description = """Add a mate between two assembly entities selected by name. kind="coincident" makes them coincident; kind="distance" sets a gap (distance_mm). Entity names follow SolidWorks selection-id syntax (e.g. "Face1<1>@Part1-1"); types are SelectByID2 style ("FACE"/"EDGE"/"VERTEX"/"PLANE")."""
    input_model = CadMateAddInput

    async def execute(self, arguments: CadMateAddInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            assembly = host.modules()["assembly"]
            connect = host.modules()["connect"]
            model = host.active_model()
            if arguments.kind == "coincident":
                mate = assembly.add_mate_coincident(model, arguments.entity1_name, arguments.entity1_type,
                                                    arguments.entity2_name, arguments.entity2_type)
            else:
                if arguments.distance_mm is None:
                    raise ValueError("distance 配合需要 distance_mm")
                mate = assembly.add_mate_distance(model, arguments.entity1_name, arguments.entity1_type,
                                                  arguments.entity2_name, arguments.entity2_type,
                                                  connect.mm(arguments.distance_mm))
            return {"status": "ok", "kind": arguments.kind,
                    "mate": str(mate) if mate is not None else None}

        return await _submit(context, "cad_mate_add", job, snapshot=False)


class CadAssemblyInspectInput(BaseModel):
    """装配检查参数。"""

    include_interference: bool = Field(default=False, description="是否运行干涉检查（装配较大时耗时）")
    top_level_only: bool = Field(default=True, description="是否仅列出顶层组件")


class CadAssemblyInspectTool(BaseTool[CadAssemblyInspectInput]):
    """列出装配组件 + 配合摘要（可选干涉检查）。"""

    name = "cad_assembly_inspect"
    description = """Inspect the active assembly: component list (name/path/suppressed), mate feature summary, and optionally run interference detection (set include_interference=True; slower on big assemblies). Read-only."""
    input_model = CadAssemblyInspectInput

    def is_read_only(self, arguments: CadAssemblyInspectInput) -> bool:
        return True

    async def execute(self, arguments: CadAssemblyInspectInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            assembly = host.modules()["assembly"]
            model = host.active_model()
            result: dict[str, Any] = {
                "status": "ok",
                "components": assembly.get_components(model, top_level_only=arguments.top_level_only),
                "mates": assembly.collect_mate_feature_summary(model),
            }
            if arguments.include_interference:
                result["interference"] = assembly.get_interference_detection(model)
            return result

        return await _submit(context, "cad_assembly_inspect", job, snapshot=False)


# === 可视化 / 审查 / 导出 ===


class CadCameraDirectInput(BaseModel):
    """相机控制参数。"""

    view: Literal["isometric", "trimetric", "dimetric", "front", "back", "top", "bottom", "right", "left", "zoomtofit"] = Field(
        description="标准视角或 zoomtofit（缩放到全图）")


class CadCameraDirectTool(BaseTool[CadCameraDirectInput]):
    """把视口切到标准视角（建模可视化镜头编排）。"""

    name = "cad_camera_direct"
    description = """Point the SolidWorks viewport at a standard view (isometric/trimetric/front/top/...) or zoom-to-fit. Use between operations to choreograph what the user sees in the live stream; each call also emits a fresh frame to the web workbench."""
    input_model = CadCameraDirectInput

    def is_read_only(self, arguments: CadCameraDirectInput) -> bool:
        return True

    async def execute(self, arguments: CadCameraDirectInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            review = host.modules()["review"]
            model = host.active_model()
            if arguments.view == "zoomtofit":
                review.clear_selection_for_preview(model)
                model.ViewZoomtofit2()
            else:
                review.set_standard_view(model, arguments.view)
            try:
                model.GraphicsRedraw2()
            except Exception:
                log.debug('边界操作失败（预期内探测）', exc_info=True)
            return {"status": "ok", "view": arguments.view}

        return await _submit(context, "cad_camera_direct", job)


class CadSnapshotInput(BaseModel):
    """快照参数。"""

    views: list[Literal["isometric", "front", "top", "right"]] = Field(
        default=["isometric"], description="要导出的视角列表（BMP，画布可直读）")


class CadSnapshotTool(BaseTool[CadSnapshotInput]):
    """立即导出当前模型多视角快照帧（可钉到画布做分镜）。"""

    name = "cad_snapshot"
    description = """Export viewport snapshot(s) of the active model as BMP frames (saved under .illusion/cad_artifacts/snapshots, pushed to the web live panel, optionally pinned as storyboard cards). Read-only."""
    input_model = CadSnapshotInput

    def is_read_only(self, arguments: CadSnapshotInput) -> bool:
        return True

    async def execute(self, arguments: CadSnapshotInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            host.modules()
            return {"status": "ok"}

        return await _submit(context, "cad_snapshot", job, snapshot=True,
                             snapshot_views=tuple(arguments.views) or ("isometric",))


class CadReviewRunInput(BaseModel):
    """完整审查参数。"""

    basename: str = Field(default="review", description="产物文件名前缀")


class CadReviewRunTool(BaseTool[CadReviewRunInput]):
    """运行完整审查：多视角预览 + 模型摘要 + review_report.json。"""

    name = "cad_review_run"
    description = """Run the vendored full review pass on the active model: multi-view BMP previews, model summary, geometry measurements and a review_report.json under .illusion/cad_artifacts/review/. Read-only; call after finishing a design iteration to verify the result before showing the user."""
    input_model = CadReviewRunInput

    def is_read_only(self, arguments: CadReviewRunInput) -> bool:
        return True

    async def execute(self, arguments: CadReviewRunInput, context: ToolExecutionContext) -> ToolResult:
        from illusion_forge.cad.canvas_store import artifacts_root

        def job(host: SolidWorksHost) -> dict[str, Any]:
            review = host.modules()["review"]
            model = host.active_model()
            out_dir = artifacts_root(Path(context.cwd)) / "review"
            report = review.run_review(model, str(out_dir), basename=arguments.basename)
            return {"status": "ok", "report": report}

        return await _submit(context, "cad_review_run", job, snapshot=False)


class CadExportInput(BaseModel):
    """导出参数。"""

    format: Literal["step", "stl", "iges", "pdf", "dxf"] = Field(description="导出格式")
    output_path: str = Field(description="输出文件绝对路径")


class CadExportTool(BaseTool[CadExportInput]):
    """把活动文档导出为 STEP/STL/IGES/PDF/DXF。"""

    name = "cad_export"
    description = """Export the active document to step/stl/iges/pdf/dxf at the given absolute path (parent dir must exist). Useful for handing geometry to the headless preview stage or external tooling."""
    input_model = CadExportInput

    async def execute(self, arguments: CadExportInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            export = host.modules()["export"]
            model = host.active_model()
            exporters = {
                "step": export.export_to_step,
                "stl": export.export_to_stl,
                "iges": export.export_to_iges,
                "pdf": export.export_to_pdf,
                "dxf": export.export_to_dxf,
            }
            exporters[arguments.format](model, arguments.output_path)
            return {"status": "ok", "format": arguments.format, "output": arguments.output_path}

        return await _submit(context, "cad_export", job, snapshot=False)


def create_modeling_tools() -> list[BaseTool[Any]]:
    """返回 M2 建模工具列表（会话类型为工作台时注册）。"""
    return [
        # 会话
        CadConnectTool(),
        CadSessionStatusTool(),
        CadNewDocumentTool(),
        CadOpenDocumentTool(),
        CadSaveDocumentTool(),
        CadCloseDocumentsTool(),
        # 零件
        CadSketchAddTool(),
        CadFeatureExtrudeTool(),
        CadFeatureRevolveTool(),
        CadFeatureFilletTool(),
        CadFeatureChamferTool(),
        CadFeaturePatternTool(),
        CadFeatureShellTool(),
        CadFeatureMirrorTool(),
        CadFeatureRibTool(),
        CadHoleCreateTool(),
        CadDimensionUpdateTool(),
        # 装配
        CadComponentAddTool(),
        CadMateAddTool(),
        CadAssemblyInspectTool(),
        # 可视化 / 审查 / 导出
        CadCameraDirectTool(),
        CadSnapshotTool(),
        CadReviewRunTool(),
        CadExportTool(),
    ]
