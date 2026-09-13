"""讨论期 3D 预览适配层。

把友善的特征参数（盒体/圆柱组合）翻译成 vendored 无头模块的
NeutralCadDocument（``.cadstudio.json``）格式，并产出画布可渲染的 GLB：

    - 始终用 vendored 网格原语 + 本包 glb_writer 生成带放置位置的 GLB
      （上游网格原语以原点为中心，这里按 parameters.position 平移）；
    - 同时经 vendored export_headless 请求 cadstudio/step/iges——OCP
      运行时可用时会产出真实 B-Rep 的 STEP/IGES（后续导入 SolidWorks），
      不可用时记入 limitations，不伪造成功。

上游 OCCT 服务的 GLB 暂不使用：其几何暂不读取 position，多特征
会叠在原点；讨论期以本适配层的放置版 GLB 为准。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from illusion_forge.cad.glb_writer import Triangle, write_glb
from illusion_forge.cad.vendor import headless_cad_writer as headless

# 支持的无头特征类型 → 网格原语（复用上游实现，保证与交付端几何一致）
_MESH_PRIMITIVES: dict[str, Any] = {
    "box": headless._box_mesh,
    "cylinder": headless._cylinder_mesh,
}


def sanitize_name(name: str) -> str:
    """把用户/模型给的名称清洗为安全的文件名主干。"""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip())
    cleaned = cleaned.strip("_") or "preview"
    return cleaned[:64]


def _build_document(name: str, features: list[dict[str, Any]], units: str) -> dict[str, Any]:
    """构造 NeutralCadDocument（上游 _validate_document 认可的最小结构）。"""
    document: dict[str, Any] = {
        "documentId": name,
        "units": units,
        "features": [],
    }
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise TypeError(f"features[{index}] 必须是 object")
        kind = str(feature.get("type") or "").lower()
        if kind not in _MESH_PRIMITIVES:
            raise TypeError(
                f"features[{index}].type 暂只支持: {', '.join(sorted(_MESH_PRIMITIVES))}"
            )
        raw_params = feature.get("parameters")
        parameters: dict[str, Any] = dict(raw_params) if isinstance(raw_params, dict) else {}
        position = feature.get("position") if isinstance(feature.get("position"), list) else None
        document["features"].append(
            {
                "id": str(feature.get("id") or f"{kind}_{index + 1}"),
                "type": kind,
                "operation": str(feature.get("operation") or "add").lower(),
                "parameters": dict(parameters),
                # position 供本适配层网格放置使用；上游校验允许额外键
                "position": [float(v) for v in (position or [0.0, 0.0, 0.0])],
            }
        )
    return document


def _positioned_triangles(document: dict[str, Any]) -> tuple[list[Triangle], list[str]]:
    """按 feature 放置位置生成组合网格（仅 add 操作，布尔操作记入限制）。"""
    triangles: list[Triangle] = []
    limitations: list[str] = []
    for feature in document["features"]:
        operation = str(feature.get("operation") or "add").lower()
        if operation not in {"add", "new", "union"}:
            limitations.append(
                f"特征 {feature['id']} 的 operation={operation} 无头网格不支持，已跳过"
            )
            continue
        params = headless._feature_params(feature)
        kind = str(feature["type"])
        if kind == "box":
            mesh = headless._box_mesh(
                float(params.get("length", 10)),
                float(params.get("width", 10)),
                float(params.get("height", 10)),
            )
        else:
            mesh = headless._cylinder_mesh(
                float(params.get("radius", 5)),
                float(params.get("height", 10)),
                int(params.get("segments", 48)),
            )
        ox, oy, oz = (feature.get("position") or [0.0, 0.0, 0.0])
        triangles.extend(
            (
                (a[0] + ox, a[1] + oy, a[2] + oz),
                (b[0] + ox, b[1] + oy, b[2] + oz),
                (c[0] + ox, c[1] + oy, c[2] + oz),
            )
            for a, b, c in mesh
        )
    return triangles, limitations


def build_preview(
    name: str,
    features: list[dict[str, Any]],
    out_dir: Path,
    units: str = "mm",
) -> dict[str, Any]:
    """生成讨论期预览产物（GLB 必有，STEP/IGES 视 OCP 可用性）。

    Args:
        name: 预览名称（同时用作 documentId 与文件名主干）
        features: 特征列表 [{type: box|cylinder, operation, parameters, position}]
        out_dir: 产物目录（不存在时创建）
        units: 单位标注（默认 mm）

    Returns:
        dict: {status, name, artifacts, bounds, limitations, missingFormats}
    """
    safe_name = sanitize_name(name)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    document = _build_document(safe_name, features, units)
    document_path = out_dir / f"{safe_name}.cadstudio.json"
    document_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 1) vendored 无头导出：cadstudio 必有；step/iges 依赖 OCP（缺失记 limitations）
    occt_formats = ["step", "iges"] if _occt_enabled() else []
    exchange = headless.export_headless(document_path, out_dir, ["cadstudio", *occt_formats])

    # 2) 带放置位置的 GLB（画布预览真源）——固定路径覆盖写：画布节点
    #    data.glb_path 按路径引用，版本化文件名会让已钉卡片的链接失效
    triangles, mesh_limitations = _positioned_triangles(document)
    glb_path = out_dir / f"{safe_name}.glb"
    bounds = write_glb(glb_path, safe_name, triangles)

    artifacts: dict[str, str | None] = {"glb": str(glb_path), "cadstudio": str(document_path)}
    for item in exchange.get("artifacts") or []:
        if item.get("kind") == "step":
            artifacts["step"] = item.get("path")
        elif item.get("kind") == "iges":
            artifacts["iges"] = item.get("path")

    limitations = [*mesh_limitations, *(exchange.get("limitations") or [])]
    missing = [f for f in (exchange.get("missingFormats") or []) if f in {"step", "iges"}]
    return {
        "status": "pass" if triangles else "blocked",
        "name": safe_name,
        "artifacts": artifacts,
        "bounds": bounds,
        "limitations": limitations,
        "missingFormats": missing,
    }


def _occt_enabled() -> bool:
    """OCP 运行时是否可用（决定是否请求 STEP/IGES 交换格式）。"""
    import importlib.util

    return importlib.util.find_spec("OCP") is not None
