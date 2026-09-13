"""CAD 深化工具域（M4）。

三组能力：

1. **方案卡 ↔ 实机 lineage**——把画布方案卡与 SolidWorks 实际模型绑定为
   血缘关系（`cad_document_link`），并按命名尺寸做"设计意图 vs 实机"差异
   对比（`cad_dimension_diff`）：方案卡 data.params 约定
   ``{"D1@Sketch1": 50.0, ...}``（毫米），对比工具回读实机尺寸逐项给出
   匹配/偏差。
2. **多文档**——列出/切换打开的文档；切换由轮询自动感知（Motion 槽位
   等文档级 COM 状态随之失效）。
3. **钣金/焊件**——基体法兰（可制造参数校验）与焊件切割清单（证据 +
   CSV 导出）。

约定：画布侧真源仍是 CanvasStore；lineage 信息写在节点 data 上
（model_path/model_title/linked_at/params），前端方案卡渲染血缘徽章。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from illusion_forge.cad.canvas_store import CanvasStore
from illusion_forge.cad.host import DEFAULT_OP_TIMEOUT, SolidWorksHost
from illusion_forge.cad.tools.modeling import _error_result, _json_result, _submit
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult


def _update_node_data(cwd: Path, session_id: str | None, node_id: str, data: dict[str, Any]) -> None:
    """把血缘信息合并进画布节点 data（画布侧真源更新）。"""
    CanvasStore.for_session(cwd, session_id).apply_op({
        "action": "update_node",
        "node_id": node_id,
        "data": data,
    })


# === lineage：方案卡 ↔ 实机 ===


class CadDocumentLinkInput(BaseModel):
    """血缘绑定参数。"""

    node_id: str = Field(description="要绑定实机模型的画布节点 id（通常是方案分支卡）")
    record_params: bool = Field(default=True, description="是否把 data.params 记为设计意图基线（供 diff）")


class CadDocumentLinkTool(BaseTool[CadDocumentLinkInput]):
    """把 SolidWorks 当前活动文档绑定为画布方案卡的实机实现。"""

    name = "cad_document_link"
    description = """Bind the ACTIVE SolidWorks document to a canvas variant card as its realized model (lineage): writes model_path/model_title/linked_at into the node data, and snapshots data.params as the design-intent baseline for later cad_dimension_diff.

Typical flow: discuss variant on canvas → build it in SolidWorks → cad_document_link(variant_node_id). Rendered as a "linked model" badge on the card."""
    input_model = CadDocumentLinkInput

    async def execute(self, arguments: CadDocumentLinkInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            host.modules()
            document = host.document_info()
            if not document:
                raise ValueError("SolidWorks 中没有活动文档可绑定")
            params_snapshot: dict[str, Any] | None = None
            if arguments.record_params:
                existing = CanvasStore.for_session(context.cwd, context.metadata.get("session_id")).get_doc()
                node = next((n for n in existing["nodes"] if n["id"] == arguments.node_id), None)
                if node is None:
                    raise ValueError(f"画布节点不存在: {arguments.node_id}")
                raw = node["data"].get("params")
                params_snapshot = dict(raw) if isinstance(raw, dict) else None
            return {
                "status": "ok",
                "model_path": document.get("path") or "",
                "model_title": document.get("title") or "",
                "params_baseline": params_snapshot,
            }

        try:
            payload = await SolidWorksHost.instance().run("cad_document_link", job, timeout=DEFAULT_OP_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 — 宿主异常转结构化错误码
            return _error_result(exc, "cad_document_link")

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        data: dict[str, Any] = {
            "model_path": payload["model_path"],
            "model_title": payload["model_title"],
            "linked_at": now,
        }
        if payload.get("params_baseline") is not None:
            data["params"] = payload["params_baseline"]
        try:
            _update_node_data(context.cwd, context.metadata.get("session_id"), arguments.node_id, data)
        except ValueError as exc:
            return _json_result({"status": "failed", "error": str(exc)}, is_error=True)
        payload["node_data"] = data
        return _json_result(payload)


class CadDimensionDiffInput(BaseModel):
    """设计意图 vs 实机差异对比参数。"""

    node_id: str = Field(description="带 data.params 基线的画布节点 id（由 cad_document_link 记录）")
    extra_dimensions: list[str] = Field(default_factory=list, description="额外要读取的尺寸名（如 \"D2@Sketch1\"）")
    tolerance_mm: float = Field(default=0.001, gt=0, description="判定匹配的容差（毫米）")


class CadDimensionDiffTool(BaseTool[CadDimensionDiffInput]):
    """对比画布方案参数与实机命名尺寸（设计意图 ↔ 实机 diff）。"""

    name = "cad_dimension_diff"
    description = """Compare a variant card's design-intent parameters (node data.params, e.g. {"D1@Sketch1": 50}) against the ACTUAL named dimensions of the active SolidWorks document: per-dimension expected/actual_mm/delta and match status. Also reads extra_dimensions. Read-only — the core of variant↔model lineage diff."""
    input_model = CadDimensionDiffInput

    def is_read_only(self, arguments: CadDimensionDiffInput) -> bool:
        return True

    async def execute(self, arguments: CadDimensionDiffInput, context: ToolExecutionContext) -> ToolResult:
        doc = CanvasStore.for_session(context.cwd, context.metadata.get("session_id")).get_doc()
        node = next((n for n in doc["nodes"] if n["id"] == arguments.node_id), None)
        if node is None:
            return _json_result({"status": "failed", "error": f"画布节点不存在: {arguments.node_id}"}, is_error=True)
        expected = node["data"].get("params") if isinstance(node["data"].get("params"), dict) else {}
        names = sorted({*expected.keys(), *arguments.extra_dimensions})

        def job(host: SolidWorksHost) -> dict[str, Any]:
            host.modules()
            actual = host.read_dimensions_mm(names) if names else {}
            return {"status": "ok", "actual": actual}

        try:
            payload = await SolidWorksHost.instance().run("cad_dimension_diff", job, timeout=DEFAULT_OP_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 — 宿主异常转结构化错误码
            return _error_result(exc, "cad_dimension_diff")
        actual = payload.get("actual") or {}
        rows: list[dict[str, Any]] = []
        mismatched = 0
        for name in names:
            actual_value = actual.get(name)
            expected_value = expected.get(name)
            row: dict[str, Any] = {"dimension": name, "expected_mm": expected_value}
            if isinstance(actual_value, dict):
                row.update({"actual_mm": None, "status": "missing", "error": actual_value.get("error")})
                mismatched += 1
            elif not isinstance(actual_value, (int, float)):
                row.update({"actual_mm": None, "status": "missing", "error": "尺寸值不是数值"})
                mismatched += 1
            else:
                row["actual_mm"] = actual_value
                if expected_value is None:
                    row["status"] = "actual_only"
                elif abs(float(actual_value) - float(expected_value)) <= arguments.tolerance_mm:
                    row["status"] = "match"
                else:
                    row["status"] = "mismatch"
                    row["delta_mm"] = round(float(actual_value) - float(expected_value), 6)
                    mismatched += 1
            rows.append(row)
        payload["rows"] = rows
        payload["summary"] = {
            "total": len(rows),
            "match": sum(1 for r in rows if r["status"] == "match"),
            "mismatch": mismatched,
        }
        payload["model_title"] = (node["data"] or {}).get("model_title")
        return _json_result(payload)


# === 多文档 ===


class CadDocumentsListInput(BaseModel):
    """列出打开文档无参数。"""


class CadDocumentsListTool(BaseTool[CadDocumentsListInput]):
    """枚举 SolidWorks 中打开的全部文档（标记活动者）。"""

    name = "cad_documents_list"
    description = """List ALL documents currently open in the connected SolidWorks session (title/path/type, with the active one flagged). Use it to plan work across multiple open documents; snapshot/tree/selection always follow the ACTIVE document, switch with cad_document_activate. Read-only."""
    input_model = CadDocumentsListInput

    def is_read_only(self, arguments: CadDocumentsListInput) -> bool:
        return True

    async def execute(self, arguments: CadDocumentsListInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            host.modules()
            return {"status": "ok", "documents": host.list_documents()}

        return await _submit(context, "cad_documents_list", job, snapshot=False)


class CadDocumentActivateInput(BaseModel):
    """切换文档参数。"""

    title: str = Field(description="文档标题（cad_documents_list 返回的 title）")


class CadDocumentActivateTool(BaseTool[CadDocumentActivateInput]):
    """切换 SolidWorks 活动文档（快照/特征树/选中项随之跟随）。"""

    name = "cad_document_activate"
    description = """Make another open document active (by title from cad_documents_list). All subsequent cad_* tools, snapshots, tree reads and the selection poll operate on the newly active document. Motion-study slot is invalidated automatically."""
    input_model = CadDocumentActivateInput

    async def execute(self, arguments: CadDocumentActivateInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            connect = host.modules()["connect"]
            model = connect.get_com_member(host.sw, "ActivateDoc3", arguments.title, True, 0,
                                           connect.VARIANT(__import__("pythoncom").VT_BYREF | __import__("pythoncom").VT_I4, 0))
            if model is None:
                raise ValueError(f"切换失败，找不到文档: {arguments.title}")
            info = host.document_info()
            return {"status": "ok", "activated": info}

        return await _submit(context, "cad_document_activate", job)


# === 钣金 / 焊件 ===


class CadSheetMetalBaseFlangeInput(BaseModel):
    """基体法兰参数（长度毫米）。"""

    sketch_name: str = Field(description="轮廓草图名（开放折线生成轮廓法兰，闭合轮廓生成平板基体）")
    thickness_mm: float = Field(gt=0, description="钣金厚度（毫米）")
    bend_radius_mm: float = Field(default=2.0, ge=0, description="折弯半径（毫米）")
    depth_mm: float = Field(gt=0, description="法兰深度（毫米）")
    k_factor: float = Field(default=0.42, gt=0, lt=1, description="K 因子（中性层位置）")


class CadSheetMetalBaseFlangeTool(BaseTool[CadSheetMetalBaseFlangeInput]):
    """从草图创建原生钣金基体法兰（可制造参数进 COM 前校验）。"""

    name = "cad_sheet_metal_base_flange"
    description = """Create a native sheet-metal base flange from an existing sketch (open polyline → contour flange; closed profile → flat base). Manufacturing params validated before COM: thickness/bend_radius/depth in mm, K-factor in (0,1). Requires cad_sketch_add first."""
    input_model = CadSheetMetalBaseFlangeInput

    async def execute(self, arguments: CadSheetMetalBaseFlangeInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            sheetmetal = host.modules()["sheetmetal"]
            connect = host.modules()["connect"]
            model = host.active_model()
            mm = connect.mm
            spec = sheetmetal.BaseFlangeSpec(
                thickness=mm(arguments.thickness_mm),
                bend_radius=mm(arguments.bend_radius_mm),
                depth=mm(arguments.depth_mm),
                k_factor=arguments.k_factor,
            )
            feature = sheetmetal.create_base_flange(model, arguments.sketch_name, spec)
            return {"status": "ok", "feature": str(feature) if feature is not None else None,
                    "thickness_mm": arguments.thickness_mm, "depth_mm": arguments.depth_mm}

        return await _submit(context, "cad_sheet_metal_base_flange", job, pin=True,
                             card_title=f"钣金基体 {arguments.thickness_mm}mm")


class CadSheetMetalEvidenceInput(BaseModel):
    """钣金证据无参数。"""


class CadSheetMetalEvidenceTool(BaseTool[CadSheetMetalEvidenceInput]):
    """收集活动钣金件证据（厚度/折弯系数/折弯列表）。"""

    name = "cad_sheet_metal_evidence"
    description = """Collect sheet-metal audit evidence from the active part (thickness, bend allowance settings, flat-pattern state). Read-only."""
    input_model = CadSheetMetalEvidenceInput

    def is_read_only(self, arguments: CadSheetMetalEvidenceInput) -> bool:
        return True

    async def execute(self, arguments: CadSheetMetalEvidenceInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            sheetmetal = host.modules()["sheetmetal"]
            return {"status": "ok", "evidence": sheetmetal.sheet_metal_evidence(host.active_model())}

        return await _submit(context, "cad_sheet_metal_evidence", job, snapshot=False)


class CadWeldmentCutListInput(BaseModel):
    """焊件切割清单参数。"""

    output_csv: str | None = Field(default=None, description="可选：切割清单 CSV 输出绝对路径")
    create_missing: bool = Field(default=False, description="文档缺少切割清单时是否创建")


class CadWeldmentCutListTool(BaseTool[CadWeldmentCutListInput]):
    """更新并导出焊件切割清单（可选 CSV，交付 BOM 证据链）。"""

    name = "cad_weldment_cut_list"
    description = """Update the weldment cut list of the active part and collect evidence (bodies, lengths, properties); optionally export a CSV at output_csv. Read-only on geometry."""
    input_model = CadWeldmentCutListInput

    def is_read_only(self, arguments: CadWeldmentCutListInput) -> bool:
        return True

    async def execute(self, arguments: CadWeldmentCutListInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            weldment = host.modules()["weldment"]
            model = host.active_model()
            evidence = weldment.weldment_evidence(model, create_missing_cut_list=arguments.create_missing)
            result: dict[str, Any] = {"status": "ok", "evidence": evidence}
            if arguments.output_csv:
                csv_path = weldment.export_cut_list_csv(evidence, arguments.output_csv)
                result["csv"] = str(csv_path)
            return result

        return await _submit(context, "cad_weldment_cut_list", job, snapshot=False)


def create_production_tools() -> list[BaseTool[Any]]:
    """返回 M4 深化工具列表（会话类型为工作台时注册）。"""
    return [
        # lineage
        CadDocumentLinkTool(),
        CadDimensionDiffTool(),
        # 多文档
        CadDocumentsListTool(),
        CadDocumentActivateTool(),
        # 钣金 / 焊件
        CadSheetMetalBaseFlangeTool(),
        CadSheetMetalEvidenceTool(),
        CadWeldmentCutListTool(),
    ]
