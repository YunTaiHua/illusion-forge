"""CAD 协作闭环工具域（M3）。

四组能力：

1. **cad_python 逃生舱**——在宿主 STA 线程内执行任意 Python，预置
   ``sw``/``model``/vendored sw_* 模块/``mm``/``deg``/``VARIANT`` 命名空间，
   覆盖上游 SKILL.md 的"未封装 API 规则"：模型可以调用任何没被工具封装的
   IModelDoc2/IModelDocExtension API。与建模工具共享同一 COM apartment，
   对象无需封送。
2. **配置族/属性**——inspect/activate/create 配置、自定义属性写入。
3. **交付**——BOM CSV 导出、Pack and Go。
4. **Motion / 外观 / 工程图**——旋转马达、计算播放、外观着色、工程图生成
   /结构检查/PDF 导出。

权限说明：cad_python 与 save/close/pack_and_go 类工具为变更类（MEDIUM），
默认逐次确认；只读检查类（config inspect / drawing inspect）免确认。
用户可在 settings.permission.allowed_tools 预放行高频工具。
"""

from __future__ import annotations

import ast
import contextlib
import io
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from illusion_forge.cad.host import CadHostError, SolidWorksHost
from illusion_forge.cad.tools.modeling import _error_result, _json_result, _submit
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult

# === cad_python 逃生舱 ===


class CadPythonInput(BaseModel):
    """宿主线程内 Python 执行参数。"""

    code: str = Field(min_length=1, description="要执行的 Python 代码。预置变量：sw(ISldWorks)、model(活动文档)、"
                    "host(会话宿主)、sw_part/sw_assembly/sw_connect/sw_review/sw_export/sw_docdata(vendored 模块)、"
                    "mm()/deg()(单位换算)、VARIANT/pythoncom。表达式代码直接返回其值；"
                    "语句代码可给 result 变量作为返回值")
    timeout_seconds: float = Field(default=60, ge=5, le=300, description="超时秒数")



def _error_hint(exc: Exception) -> str:
    """按异常类型给自纠错线索（cad_python 的编译器错误提示）。"""
    text = str(exc)
    if isinstance(exc, AttributeError):
        if "'SolidWorksHost' object" in text:
            return ("host 常用属性：host.sw / host.model（活动文档，可能为 None）/ host.last_motion_study；"
                    "命名空间已直接预置 model 与 sw，无需经 host 取")
        return ("属性不存在——API 名称与直觉常有出入：特征类型名是 GetTypeName2（不是 TypeName）；"
                "标题 GetTitle()；路径是属性 GetPathName（不加括号）；"
                "拿不准用 safe_gcm(obj, '成员名', default=None) 探测，遍历特征用 iter_features(model)")
    if "找不到成员" in text or "Member not found" in text:
        return ("COM 成员或参数不匹配：该成员可能是属性而非方法（obj.Name 而非 obj.Name()），"
                "或参数数量/类型不对；二态成员统一用 gcm(obj, 'Name', *args)")
    if "找不到元素" in text or "Element not found" in text or "-2147319765" in text:
        return "pywin32 动态派发怪癖（成员存在但类型信息缺失）：改用 gcm(obj, '成员名', *参数) 重试即可"
    if "not callable" in text:
        return "调用的成员是属性不是方法：去掉括号，或改用 gcm(obj, '成员名') 自动处理二态"
    if "-2147352561" in text or "非选择性的参数" in text or "PARAMNOTFOUND" in text:
        return ("COM 方法缺少必选参数或参数序号不匹配：检查 API 签名中每个参数的位置和类型；"
                "二态成员统一用 gcm(obj, 'Name', *args)；遍历特征用 iter_features(model)")
    # 兜底：永远给线索，不让 LLM 面对 null hint 无从修正
    return ("COM 调用失败：属性用 obj.Name（不加括号），方法用 "
            "gcm(obj, 'Name', *args)，safe_gcm(obj, 'Name', default=None) 安全探测，"
            "iter_features(model) 遍历特征；特征类型名用 GetTypeName2")

class CadPythonTool(BaseTool[CadPythonInput]):
    """在 SolidWorks COM 宿主线程内执行任意 Python（未封装 API 逃生舱）。

    安全边界（刻意设计，与平台既有能力对齐）：本工具拥有完整 Python
    builtins（含 __import__/open），能力上限等同平台的 bash/powershell
    工具——两者都受同一权限体系门禁（MEDIUM 变更类默认逐次确认）。
    不做 builtins 裁剪：那只会破坏合法用法（导出文件、os.path 探测等），
    而 bash 的存在使裁剪不构成实际安全增益。会话内还可通过
    settings.permission.denied_tools 完全禁用本工具。
    """

    name = "cad_python"
    description = """Execute arbitrary Python INSIDE the SolidWorks COM host thread — the escape hatch for SolidWorks APIs not covered by the dedicated cad_* tools.

Pre-bound namespace: `sw` (ISldWorks), `model` (active IModelDoc2, may be None), `host` (session host), vendored modules `sw_part/sw_assembly/sw_connect/sw_review/sw_export/sw_docdata/sw_delivery/sw_motion/sw_appearance/sw_drawing`, helpers `mm()/deg()` (mm/deg→m/rad), `VARIANT`, `pythoncom`.

Rules: an expression returns its value directly; for statements set a `result` variable to return data. Raw SolidWorks API lengths are in METERS — wrap millimeter values with mm(). Keep it short (blocks the serial CAD queue); prefer dedicated cad_* tools when one exists. Example: `result = model.Extension.CreateDimension(...)`.

Cheat sheet (pre-bound helpers avoiding pywin32 pitfalls): `gcm(obj,'Name',*args)` property/method-safe access (PREFER over obj.Name()); `safe_gcm(obj,'Name',default=None)` non-raising probe; `iter_features(model)`; feature type name is GetTypeName2 (NOT TypeName); geometry/bbox prefer cad_review_run. On failure read the `hint` field and self-correct."""
    input_model = CadPythonInput

    async def execute(self, arguments: CadPythonInput, context: ToolExecutionContext) -> ToolResult:
        code = arguments.code
        timeout = arguments.timeout_seconds

        def job(host: SolidWorksHost) -> dict[str, Any]:
            modules = host.modules()
            connect = modules["connect"]
            namespace: dict[str, Any] = {
                "sw": host._sw,
                "model": host.active_model(required=False),
                "host": host,
                "mm": connect.mm,
                "deg": connect.deg,
                "VARIANT": connect.VARIANT,
                "pythoncom": __import__("pythoncom"),
                # === vendored 助手（属性/方法二态、动态派发怪癖的解药）===
                "gcm": connect.get_com_member,            # gcm(obj, "Name", *args)
                "safe_gcm": connect.safe_get_com_member,  # safe_gcm(obj, "Name", default=None)
                "iter_features": modules["sheetmetal"].iter_features,
                "delete_feature": host.delete_feature,  # 删除特征（勿直接裸调 DeleteFeature2）
                "sw_part": modules["part"],
                "sw_assembly": modules["assembly"],
                "sw_connect": modules["connect"],
                "sw_review": modules["review"],
                "sw_export": modules["export"],
                "sw_docdata": modules["docdata"],
                "sw_delivery": modules.get("delivery"),
                "sw_motion": modules.get("motion"),
                "sw_appearance": modules.get("appearance"),
                "sw_drawing": modules.get("drawing"),
                "result": None,
            }
            buffer = io.StringIO()
            try:
                tree = ast.parse(code)
            except SyntaxError as exc:
                return {"status": "failed", "error": f"Python 语法错误: {exc}"}
            is_expression = len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr)
            compiled = compile(code, "<cad_python>", "eval" if is_expression else "exec")
            try:
                with contextlib.redirect_stdout(buffer):
                    if is_expression:
                        value = eval(compiled, namespace)
                    else:
                        exec(compiled, namespace)  # noqa: S102 — 逃生舱既定能力
                        value = None
            except Exception as exc:  # noqa: BLE001 — 任意用户代码异常必须转结构化返回
                return {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "hint": _error_hint(exc),
                    "stdout": buffer.getvalue()[-4000:],
                }
            result = value if is_expression else namespace.get("result")
            return {
                "status": "ok",
                "result": repr(result)[:2000] if result is not None else None,
                "stdout": buffer.getvalue()[-4000:],
            }

        try:
            payload = await SolidWorksHost.instance().run("cad_python", job, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — 宿主异常转结构化错误码
            return _error_result(exc, "cad_python")
        is_error = payload.get("status") == "failed"
        return _json_result(payload, is_error=is_error)


# === 配置族 / 自定义属性 ===


class CadConfigInspectInput(BaseModel):
    """配置族检查无参数。"""


class CadConfigInspectTool(BaseTool[CadConfigInspectInput]):
    """列出活动文档的配置族与各自状态。"""

    name = "cad_config_inspect"
    description = """List all configurations of the active document (names, comments, alternate names, parent). Read-only."""
    input_model = CadConfigInspectInput

    def is_read_only(self, arguments: CadConfigInspectInput) -> bool:
        return True

    async def execute(self, arguments: CadConfigInspectInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            docdata = host.modules()["docdata"]
            return {"status": "ok", "configurations": docdata.inspect_configurations(host.active_model())}

        return await _submit(context, "cad_config_inspect", job, snapshot=False)


class CadConfigActivateInput(BaseModel):
    """激活配置参数。"""

    configuration_name: str = Field(description="要激活的配置名")
    rebuild: bool = Field(default=True, description="激活后是否 rebuild")


class CadConfigActivateTool(BaseTool[CadConfigActivateInput]):
    """切换活动配置。"""

    name = "cad_config_activate"
    description = """Switch the active configuration of the active document (e.g. to a different size variant)."""
    input_model = CadConfigActivateInput

    async def execute(self, arguments: CadConfigActivateInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            docdata = host.modules()["docdata"]
            evidence = docdata.activate_configuration(host.active_model(), arguments.configuration_name,
                                                      rebuild=arguments.rebuild)
            return {"status": "ok", "evidence": evidence}

        return await _submit(context, "cad_config_activate", job, snapshot=False)


class CadConfigCreateInput(BaseModel):
    """新建配置参数。"""

    configuration_name: str = Field(description="新配置名")
    comment: str = Field(default="", description="说明")
    activate: bool = Field(default=True, description="创建后是否立即激活")


class CadConfigCreateTool(BaseTool[CadConfigCreateInput]):
    """新建文档配置（配置族驱动系列化设计）。"""

    name = "cad_config_create"
    description = """Create a new configuration on the active document (for family-of-parts design); optionally activate it. Combine with cad_dimension_update to drive per-configuration dimensions."""
    input_model = CadConfigCreateInput

    async def execute(self, arguments: CadConfigCreateInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            docdata = host.modules()["docdata"]
            evidence = docdata.create_configuration(host.active_model(), arguments.configuration_name,
                                                    comment=arguments.comment, activate=arguments.activate)
            return {"status": "ok", "evidence": evidence}

        return await _submit(context, "cad_config_create", job, snapshot=False)


class CadPropertiesSetInput(BaseModel):
    """自定义属性参数。"""

    properties: dict[str, str] = Field(min_length=1, description="属性名 → 值（文本）")
    configuration_name: str = Field(default="", description="配置级属性目标配置；空 = 文件级")
    save: bool = Field(default=False, description="写入后是否保存")


class CadPropertiesSetTool(BaseTool[CadPropertiesSetInput]):
    """写入自定义属性（BOM/交付追溯的数据源）。"""

    name = "cad_properties_set"
    description = """Write custom properties (name→value map) on the active document, file-level or per-configuration. These feed BOM columns and Pack and Go traceability. Each value is read back for verification."""
    input_model = CadPropertiesSetInput

    async def execute(self, arguments: CadPropertiesSetInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            docdata = host.modules()["docdata"]
            evidence = docdata.set_custom_properties(host.active_model(), arguments.properties,
                                                     configuration_name=arguments.configuration_name,
                                                     save=arguments.save)
            return {"status": "ok", "evidence": evidence}

        return await _submit(context, "cad_properties_set", job, snapshot=False)


# === 交付 ===


class CadBomExportInput(BaseModel):
    """BOM 导出参数。"""

    output_path: str = Field(description="CSV 输出绝对路径")
    include_excluded: bool = Field(default=False, description="是否包含被排除件")


class CadBomExportTool(BaseTool[CadBomExportInput]):
    """导出装配体 BOM 为 UTF-8 CSV（含 SHA-256 证据）。"""

    name = "cad_bom_export"
    description = """Export the active assembly's BOM to a UTF-8 CSV (part number, quantity, description columns resolved from custom properties) with file-size + SHA-256 evidence. Requires an assembly document."""
    input_model = CadBomExportInput

    async def execute(self, arguments: CadBomExportInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            delivery = host.modules()["delivery"]
            evidence = delivery.export_assembly_bom_csv(host.active_model(), arguments.output_path,
                                                        include_excluded=arguments.include_excluded,
                                                        overwrite=True)
            return {"status": "ok", "evidence": evidence}

        return await _submit(context, "cad_bom_export", job, snapshot=False)


class CadPackAndGoInput(BaseModel):
    """Pack and Go 参数。"""

    output_dir: str = Field(description="输出目录（自动收集依赖）")
    include_drawings: bool = Field(default=True, description="是否包含关联工程图")
    flatten: bool = Field(default=False, description="是否拍平目录结构")


class CadPackAndGoTool(BaseTool[CadPackAndGoInput]):
    """Pack and Go 打包（收集全部依赖，可交付归档）。"""

    name = "cad_pack_and_go"
    description = """Copy the active document with ALL dependencies (parts, sub-assemblies, optionally drawings) into an output dir via SolidWorks Pack and Go — the safe way to hand over a self-contained deliverable. Returns audit evidence of copied files."""
    input_model = CadPackAndGoInput

    async def execute(self, arguments: CadPackAndGoInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            delivery = host.modules()["delivery"]
            evidence = delivery.pack_and_go(host.active_model(), arguments.output_dir,
                                            include_drawings=arguments.include_drawings,
                                            flatten=arguments.flatten)
            return {"status": "ok", "evidence": evidence}

        return await _submit(context, "cad_pack_and_go", job, snapshot=False, timeout=300.0)


# === Motion ===


class CadMotionCreateInput(BaseModel):
    """创建 Motion Study 参数。"""

    name: str | None = Field(default=None, description="Study 名称")
    duration_seconds: float = Field(default=4.0, gt=0, le=60, description="动画时长（秒）")


class CadMotionCreateTool(BaseTool[CadMotionCreateInput]):
    """在活动装配体上创建 Motion Study（后续马达/计算共用此 study）。"""

    name = "cad_motion_create"
    description = """Create a Motion Study on the active assembly. Later cad_motion_add_motor and cad_motion_calculate calls reuse this study (kept host-side). Requires SolidWorks Motion type library (auto-located from the install dir)."""
    input_model = CadMotionCreateInput

    async def execute(self, arguments: CadMotionCreateInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            motion = host.modules()["motion"]
            study = motion.create_motion_study(host.active_model(), name=arguments.name,
                                               duration=arguments.duration_seconds)
            host.last_motion_study = study
            return {"status": "ok", "created": bool(study)}

        return await _submit(context, "cad_motion_create", job, snapshot=False)


class CadMotionAddMotorInput(BaseModel):
    """添加旋转马达参数（按圆柱面自动定位）。"""

    shaft_component: str = Field(description="轴类组件名关键字（如 \"shaft\"/\"轴\"）")
    rotor_component: str = Field(description="被驱动转子组件名关键字")
    rpm: float = Field(default=60.0, gt=0, description="转速（RPM）")
    reverse: bool = Field(default=False, description="是否反向")
    name: str | None = Field(default=None, description="马达特征名")


class CadMotionAddMotorTool(BaseTool[CadMotionAddMotorInput]):
    """通过两个组件的最大圆柱面添加匀速旋转马达。"""

    name = "cad_motion_add_motor"
    description = """Add a constant-speed rotary motor to the current Motion Study, locating the rotation axis via the largest cylindrical face of the shaft component and driving the rotor component's cylindrical face (both resolved by name keyword). Requires cad_motion_create first."""
    input_model = CadMotionAddMotorInput

    async def execute(self, arguments: CadMotionAddMotorInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            if host.last_motion_study is None:
                raise CadHostError("尚无 Motion Study，请先调用 cad_motion_create。", "cad_motion_no_study")
            motion = host.modules()["motion"]
            assembly = host.modules()["assembly"]
            model = host.active_model()
            shaft = assembly.find_component_by_name(model, arguments.shaft_component)
            rotor = assembly.find_component_by_name(model, arguments.rotor_component)
            feature = motion.add_constant_speed_rotary_motor_by_cylinders(
                host.last_motion_study, shaft, rotor,
                rpm=arguments.rpm, reverse=arguments.reverse, name=arguments.name,
            )
            return {"status": "ok", "motor": str(feature) if feature is not None else None}

        return await _submit(context, "cad_motion_add_motor", job, snapshot=False)


class CadMotionCalculateInput(BaseModel):
    """计算播放参数。"""

    play: bool = Field(default=True, description="计算后是否播放动画")


class CadMotionCalculateTool(BaseTool[CadMotionCalculateInput]):
    """计算 Motion Study 并可选播放（耗时操作）。"""

    name = "cad_motion_calculate"
    description = """Calculate the current Motion Study (and optionally play the animation). This can take a while on large assemblies — a generous timeout is applied internally."""
    input_model = CadMotionCalculateInput

    async def execute(self, arguments: CadMotionCalculateInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            if host.last_motion_study is None:
                raise CadHostError("尚无 Motion Study，请先调用 cad_motion_create。", "cad_motion_no_study")
            motion = host.modules()["motion"]
            motion.calculate_and_play(host.last_motion_study, play=arguments.play)
            return {"status": "ok", "calculated": True}

        return await _submit(context, "cad_motion_calculate", job, snapshot=False, timeout=600.0)


class CadMotionSummaryInput(BaseModel):
    """Motion 摘要无参数。"""


class CadMotionSummaryTool(BaseTool[CadMotionSummaryInput]):
    """审计 Motion Study 汇总（马达/时长/结果状态）。"""

    name = "cad_motion_summary"
    description = """Collect a summary of motion studies on the active assembly (motors, durations, result state) for delivery audit. Read-only."""
    input_model = CadMotionSummaryInput

    def is_read_only(self, arguments: CadMotionSummaryInput) -> bool:
        return True

    async def execute(self, arguments: CadMotionSummaryInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            motion = host.modules()["motion"]
            return {"status": "ok", "summary": motion.collect_motion_study_summary(host.active_model())}

        return await _submit(context, "cad_motion_summary", job, snapshot=False)


# === 外观 ===


class CadAppearanceSetInput(BaseModel):
    """外观设置参数。"""

    color: str = Field(description='颜色（十六进制如 "#8A0E0E"，或上游预设名如 "iron_red"）')
    component_keyword: str | None = Field(default=None, description="装配体模式下要着色的组件名关键字；缺省给整个文档着色")


class CadAppearanceSetTool(BaseTool[CadAppearanceSetInput]):
    """给文档或装配组件设置外观颜色（快照里立刻可见）。"""

    name = "cad_appearance_set"
    description = """Set appearance color (hex like "#8A0E0E" or a preset name) on the whole active document, or on one assembly component resolved by name keyword. Useful for highlighting changed parts in the live stream."""
    input_model = CadAppearanceSetInput

    async def execute(self, arguments: CadAppearanceSetInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            appearance = host.modules()["appearance"]
            model = host.active_model()
            if arguments.component_keyword:
                assembly = host.modules()["assembly"]
                component = assembly.find_component_by_name(model, arguments.component_keyword)
                appearance.set_component_appearance(component, arguments.color)
                return {"status": "ok", "target": arguments.component_keyword}
            appearance.set_document_appearance(model, arguments.color)
            return {"status": "ok", "target": "document"}

        return await _submit(context, "cad_appearance_set", job)


# === 工程图 ===


class CadDrawingGenerateInput(BaseModel):
    """工程图生成参数（DrawingSpec 精简面）。"""

    source_model_path: str = Field(description="源模型文件绝对路径（视图引用它）")
    model_size_mm: list[float] = Field(min_length=3, max_length=3, description="模型包围盒 [长, 宽, 高]（毫米），用于比例与视图布局")
    paper_size: Literal["A0", "A1", "A2", "A3", "A4"] = Field(default="A3", description="图纸幅面")
    projection: Literal["first_angle", "third_angle"] = Field(default="first_angle", description="投影角法")
    standard: Literal["GB_T", "ISO"] | None = Field(default=None, description="标准（GB_T 时强制 GB 图框模板）")
    scale: str | None = Field(default=None, description="期望比例（如 \"1:2\"；缺省自动）")


class CadDrawingGenerateTool(BaseTool[CadDrawingGenerateInput]):
    """按规范生成标准视图工程图（GB/ISO 图框、自适应比例布局）。"""

    name = "cad_drawing_generate"
    description = """Generate a standard-view drawing on the ACTIVE DRAWING document from a source model: sets up the sheet (GB/ISO template), plans adaptive view layout from the model bounding box (mm), creates standard views, inserts center marks. Flow: cad_new_document(drawing) → open/activate the source model context → call this. The model size must be provided — the vendored layer refuses to guess scale."""
    input_model = CadDrawingGenerateInput

    async def execute(self, arguments: CadDrawingGenerateInput, context: ToolExecutionContext) -> ToolResult:
        if not Path(arguments.source_model_path).is_file():
            return _json_result({"status": "failed", "error": f"源模型不存在: {arguments.source_model_path}"}, is_error=True)

        def job(host: SolidWorksHost) -> dict[str, Any]:
            drawing = host.modules()["drawing"]
            spec = {
                "paperSize": arguments.paper_size,
                "projection": arguments.projection,
                "modelSizeMm": list(arguments.model_size_mm),
                "scale": arguments.scale,
                "standard": arguments.standard,
            }
            report = drawing.generate_drawing_from_spec(host.active_model(), spec, arguments.source_model_path)
            status = report.get("status") if isinstance(report, dict) else None
            return {"status": status or "ok", "report": report}

        return await _submit(context, "cad_drawing_generate", job, timeout=300.0, pin=True,
                             card_title=f"工程图 {arguments.paper_size}")


class CadDrawingExportPdfInput(BaseModel):
    """工程图 PDF 导出参数。"""

    output_path: str = Field(description="PDF 输出绝对路径")
    sheet_names: list[str] | None = Field(default=None, description="要导出的图纸名；缺省全部")


class CadDrawingExportPdfTool(BaseTool[CadDrawingExportPdfInput]):
    """把活动工程图导出为 PDF。"""

    name = "cad_drawing_export_pdf"
    description = """Export the active drawing's sheets to PDF at the given absolute path. Read-only on the model content."""
    input_model = CadDrawingExportPdfInput

    def is_read_only(self, arguments: CadDrawingExportPdfInput) -> bool:
        return True

    async def execute(self, arguments: CadDrawingExportPdfInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            drawing = host.modules()["drawing"]
            drawing.export_sheet_to_pdf(host.active_model(), arguments.output_path,
                                        sheet_names=arguments.sheet_names)
            return {"status": "ok", "output": arguments.output_path}

        return await _submit(context, "cad_drawing_export_pdf", job, snapshot=False)


class CadDrawingInspectInput(BaseModel):
    """工程图结构检查无参数。"""


class CadDrawingInspectTool(BaseTool[CadDrawingInspectInput]):
    """检查活动工程图的图纸/视图/标注结构。"""

    name = "cad_drawing_inspect"
    description = """Inspect the active drawing's structure: sheets, views, scale, annotation coverage — use it to self-review a generated drawing. Read-only."""
    input_model = CadDrawingInspectInput

    def is_read_only(self, arguments: CadDrawingInspectInput) -> bool:
        return True

    async def execute(self, arguments: CadDrawingInspectInput, context: ToolExecutionContext) -> ToolResult:
        def job(host: SolidWorksHost) -> dict[str, Any]:
            drawing = host.modules()["drawing"]
            return {"status": "ok", "structure": drawing.inspect_drawing_structure(host.active_model())}

        return await _submit(context, "cad_drawing_inspect", job, snapshot=False)


def create_advanced_tools() -> list[BaseTool[Any]]:
    """返回 M3 协作闭环工具列表（会话类型为工作台时注册）。"""
    return [
        CadPythonTool(),
        # 配置族 / 属性
        CadConfigInspectTool(),
        CadConfigActivateTool(),
        CadConfigCreateTool(),
        CadPropertiesSetTool(),
        # 交付
        CadBomExportTool(),
        CadPackAndGoTool(),
        # Motion
        CadMotionCreateTool(),
        CadMotionAddMotorTool(),
        CadMotionCalculateTool(),
        CadMotionSummaryTool(),
        # 外观 / 工程图
        CadAppearanceSetTool(),
        CadDrawingGenerateTool(),
        CadDrawingExportPdfTool(),
        CadDrawingInspectTool(),
    ]
