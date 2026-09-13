"""CAD 工作台工具集。

注册进 ToolRegistry 的工具（会话类型为工作台时）：

    - cad_health_check  环境健康报告（平台/SolidWorks 探测/依赖）
    - cad_preview_build 讨论期无头 3D 预览（NeutralCadDocument → GLB/STEP）
    - canvas_add_node / canvas_update_node / canvas_remove_node
                        画布工作台节点操作（变更经 WebSocket 广播到前端）

说明：canvas_* 与 cad_preview_build 标记为只读——它们只写
``.illusion/cad_artifacts`` 设计产物与画布文档，不触碰用户代码，
默认免确认以保证"讨论-出图"循环流畅；M3 权限域细化时再分级。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import AliasChoices, BaseModel, Field

from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult

# 统一出口：所有工具结果序列化为 JSON 字符串（模型侧易于引用 id/path）


def _json_result(payload: Any, is_error: bool = False) -> ToolResult:
    return ToolResult(
        output=json.dumps(payload, ensure_ascii=False),
        is_error=is_error,
    )


# === cad_health_check ===


class CadHealthCheckInput(BaseModel):
    """健康检查无参数。"""


class CadHealthCheckTool(BaseTool[CadHealthCheckInput]):
    """报告 CAD 工作台环境健康状态。"""

    name = "cad_health_check"
    description = """Report CAD workbench environment health: platform, SolidWorks installation (registry probe, no process launch), optional dependencies (win32com/comtypes/OCP/ezdxf), and artifacts directory writability.

Call this before any CAD work to tell the user what is actually available on this machine. Never guess SolidWorks availability without calling this first."""
    input_model = CadHealthCheckInput

    def is_read_only(self, arguments: CadHealthCheckInput) -> bool:
        return True

    async def execute(self, arguments: CadHealthCheckInput, context: ToolExecutionContext) -> ToolResult:
        del arguments
        from illusion_forge.cad.canvas_store import artifacts_root
        from illusion_forge.cad.health import collect_health

        return _json_result(collect_health(artifacts_root(context.cwd)))


# === cad_preview_build ===


class PreviewFeatureInput(BaseModel):
    """单个无头预览特征。

    Attributes:
        type: 特征类型（box 盒体 / cylinder 圆柱）
        operation: 布尔语义（add 加材料；cut 等暂不支持，记入 limitations）
        id: 可选特征 id（默认按序号生成）
        parameters: 尺寸参数（box: length/width/height；cylinder: radius/height/segments）
        position: 放置位置 [x, y, z]（默认原点）
    """

    type: str = Field(
        validation_alias=AliasChoices("type", "kind"),
        description="特征类型（字段名 type，兼容 kind）：box 或 cylinder",
    )
    operation: str = Field(default="add", description="布尔语义：add（cut 暂不支持）")
    id: str | None = Field(default=None, description="可选特征 id")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="尺寸参数（box: length/width/height；cylinder: radius/height/segments）",
    )
    position: list[float] | None = Field(default=None, description="放置位置 [x, y, z]")


class CadPreviewBuildInput(BaseModel):
    """无头 3D 预览参数。

    Attributes:
        name: 预览名称（用作文件名主干）
        features: 特征列表（盒体/圆柱组合）
        units: 单位标注（默认 mm）
        pin_to_canvas: 是否同时把预览卡钉到画布（默认 True）
        connect_to: 预览卡要连线的既有画布节点 id（如方案分支卡）
    """

    name: str = Field(min_length=1, max_length=120, description="预览名称")
    features: list[PreviewFeatureInput] = Field(min_length=1, description="特征列表")
    units: str = Field(default="mm", description="单位标注")
    pin_to_canvas: bool = Field(default=True, description="是否钉到画布")
    connect_to: list[str] = Field(default_factory=list, description="连线目标节点 id")


class CadPreviewBuildTool(BaseTool[CadPreviewBuildInput]):
    """无头生成 3D 预览并（可选）钉到画布。"""

    name = "cad_preview_build"
    description = """Build a headless 3D preview artifact from box/cylinder features — NO SolidWorks required, works during the discussion phase.

Writes <workspace>/.illusion/cad_artifacts/previews/<name>/ containing a renderable .glb plus .cadstudio.json (NeutralCadDocument); STEP/IGES are added when the OCP runtime is installed. By default pins a "preview" node onto the workbench canvas so the user can inspect the 3D model.

Each feature object MUST carry a discriminator field `type` (alias `kind` accepted): {"type":"box","parameters":{"length":20,"width":20,"height":20},"position":[0,0,0]} or {"type":"cylinder","parameters":{"radius":10,"height":20}}.

Use this to turn a discussed design variant into something the user can actually look at, iterate on parameters, and finally hand off to real SolidWorks modeling. feature parameters use millimeters: box needs length/width/height, cylinder needs radius/height (segments optional, default 48). position is the [x,y,z] placement of the primitive center."""
    input_model = CadPreviewBuildInput

    def is_read_only(self, arguments: CadPreviewBuildInput) -> bool:
        # 只写 .illusion/cad_artifacts 设计产物，不触碰用户代码（见模块 docstring）
        return True

    async def execute(self, arguments: CadPreviewBuildInput, context: ToolExecutionContext) -> ToolResult:
        from illusion_forge.cad.canvas_store import CanvasStore, artifacts_root
        from illusion_forge.cad.preview import build_preview

        out_dir = artifacts_root(context.cwd) / "previews"
        try:
            result = build_preview(
                arguments.name,
                [feature.model_dump(exclude_none=True) for feature in arguments.features],
                out_dir / _safe_segment(arguments.name),
            )
        except (ValueError, OSError) as exc:
            return _json_result({"status": "failed", "error": str(exc)}, is_error=True)

        node_id: str | None = None
        if arguments.pin_to_canvas and result.get("artifacts", {}).get("glb"):
            try:
                snapshot = CanvasStore.for_session(
                    context.cwd, context.metadata.get("session_id", "")
                ).apply_op(
                    {
                        "action": "add_node",
                        "kind": "preview",
                        "title": arguments.name,
                        "body": "",
                        "data": {
                            "glb_path": result["artifacts"]["glb"],
                            "cadstudio_path": result["artifacts"].get("cadstudio"),
                            "bounds": result.get("bounds"),
                        },
                        "connect_to": arguments.connect_to,
                    }
                )
                node_id = next(
                    (
                        node["id"]
                        for node in snapshot["nodes"]
                        if node["data"].get("glb_path") == result["artifacts"]["glb"]
                    ),
                    None,
                )
            except ValueError as exc:
                result.setdefault("limitations", []).append(f"画布钉卡片失败: {exc}")

        result["canvas_node_id"] = node_id
        return _json_result(result)


def _safe_segment(name: str) -> str:
    from illusion_forge.cad.preview import sanitize_name

    return sanitize_name(name)


# === canvas_* 画布工具 ===


class CanvasAddNodeInput(BaseModel):
    """画布加节点参数。"""

    kind: str = Field(
        description='节点类型: "requirement"(需求) | "variant"(方案分支) | '
        '"preview"(3D预览, data.glb_path) | "snapshot"(截图卡) | '
        '"spec"(参数表) | "note"(备注)'
    )
    title: str = Field(default="", description="卡片标题")
    body: str = Field(default="", description="卡片正文（markdown）")
    data: dict[str, Any] = Field(default_factory=dict, description="扩展数据（如 glb_path）")
    x: float | None = Field(default=None, description="画布 X（缺省自动排布）")
    y: float | None = Field(default=None, description="画布 Y（缺省自动排布）")
    connect_to: list[str] = Field(default_factory=list, description="要连线的既有节点 id")
    node_id: str | None = Field(default=None, description="自定义节点 id（缺省自动生成）")


class CanvasAddNodeTool(BaseTool[CanvasAddNodeInput]):
    """在画布工作台上添加卡片节点。"""

    name = "canvas_add_node"
    description = """Add a card node onto the CAD workbench canvas (React Flow board shared with the user). The change is pushed live to the web UI.

Node kinds: "requirement" = user requirement/constraint card; "variant" = one design proposal (rivals can coexist for comparison); "spec" = parameter table; "preview" = 3D model card, put an absolute glb_path (from cad_preview_build output) into data; "snapshot" = screenshot card; "note" = free note.

Workflow: put requirements as requirement cards when the user states constraints; add one variant card per design direction and connect it to its requirement (connect_to); when a variant is chosen, build a 3D preview with cad_preview_build and connect the preview node to the variant card."""
    input_model = CanvasAddNodeInput

    def is_read_only(self, arguments: CanvasAddNodeInput) -> bool:
        return True

    async def execute(self, arguments: CanvasAddNodeInput, context: ToolExecutionContext) -> ToolResult:
        from illusion_forge.cad.canvas_store import CanvasStore

        try:
            _sid = context.metadata.get("session_id")
            snapshot = CanvasStore.for_session(context.cwd, _sid).apply_op(
                {"action": "add_node", **arguments.model_dump(exclude_none=True)}
            )
        except ValueError as exc:
            return _json_result({"status": "failed", "error": str(exc)}, is_error=True)
        node_id = str(arguments.node_id or "") or snapshot["nodes"][-1]["id"]
        return _json_result({"status": "ok", "node_id": node_id, "revision": snapshot["revision"]})


class CanvasUpdateNodeInput(BaseModel):
    """画布更新节点参数。"""

    node_id: str = Field(description="目标节点 id")
    title: str | None = Field(default=None, description="新标题（None 不变）")
    body: str | None = Field(default=None, description="新正文（None 不变）")
    data: dict[str, Any] | None = Field(default=None, description="替换的扩展数据（None 不变）")
    x: float | None = Field(default=None, description="新 X（需与 y 同时提供）")
    y: float | None = Field(default=None, description="新 Y（需与 x 同时提供）")


class CanvasUpdateNodeTool(BaseTool[CanvasUpdateNodeInput]):
    """更新画布上的卡片节点（方案演进、补充参数等）。"""

    name = "canvas_update_node"
    description = """Update an existing node on the CAD workbench canvas (title/body/data/position). Use it when a design evolves: refine a variant card's parameters, attach review findings, or replace a preview's glb_path after rebuilding."""
    input_model = CanvasUpdateNodeInput

    def is_read_only(self, arguments: CanvasUpdateNodeInput) -> bool:
        return True

    async def execute(self, arguments: CanvasUpdateNodeInput, context: ToolExecutionContext) -> ToolResult:
        from illusion_forge.cad.canvas_store import CanvasStore

        payload = arguments.model_dump(exclude_none=True)
        payload["action"] = "update_node"
        try:
            _sid = context.metadata.get("session_id")
            snapshot = CanvasStore.for_session(context.cwd, _sid).apply_op(payload)
        except ValueError as exc:
            return _json_result({"status": "failed", "error": str(exc)}, is_error=True)
        return _json_result({"status": "ok", "revision": snapshot["revision"]})


class CanvasRemoveNodeInput(BaseModel):
    """画布移除节点参数。"""

    node_id: str = Field(description="要移除的节点 id")


class CanvasRemoveNodeTool(BaseTool[CanvasRemoveNodeInput]):
    """从画布移除卡片节点（含关联连线）。"""

    name = "canvas_remove_node"
    description = """Remove a node (and its edges) from the CAD workbench canvas — e.g. dropping a rejected design variant after the user picks another one."""
    input_model = CanvasRemoveNodeInput

    def is_read_only(self, arguments: CanvasRemoveNodeInput) -> bool:
        return True

    async def execute(self, arguments: CanvasRemoveNodeInput, context: ToolExecutionContext) -> ToolResult:
        from illusion_forge.cad.canvas_store import CanvasStore

        try:
            _sid = context.metadata.get("session_id")
            snapshot = CanvasStore.for_session(context.cwd, _sid).apply_op(
                {"action": "remove_node", "node_id": arguments.node_id}
            )
        except ValueError as exc:
            return _json_result({"status": "failed", "error": str(exc)}, is_error=True)
        return _json_result({"status": "ok", "revision": snapshot["revision"]})


def create_cad_tools() -> list[BaseTool[Any]]:
    """返回 CAD 工作台工具列表（会话类型为工作台时注册）。

    M1：无头预览 + 画布操作 + 健康检查；M2：SolidWorks 建模工具域
    （会话/零件/装配/相机/快照/审查/导出）；M3：协作闭环（cad_python
    逃生舱/配置族/属性/交付/Motion/外观/工程图）；M4：深化（方案卡↔实机
    lineage/多文档/钣金/焊件）。
    """
    from illusion_forge.cad.tools.advanced import create_advanced_tools
    from illusion_forge.cad.tools.modeling import create_modeling_tools
    from illusion_forge.cad.tools.production import create_production_tools

    return [
        CadHealthCheckTool(),
        CadPreviewBuildTool(),
        CanvasAddNodeTool(),
        CanvasUpdateNodeTool(),
        CanvasRemoveNodeTool(),
        *create_modeling_tools(),
        *create_advanced_tools(),
        *create_production_tools(),
    ]
