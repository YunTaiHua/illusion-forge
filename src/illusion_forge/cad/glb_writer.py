"""二进制 GLB 写入器（讨论期 3D 预览，零原生依赖）。

把三角面片（与 vendored headless_cad_writer._triangles 相同的
``(Point3, Point3, Point3)`` 形态）写成 glTF 2.0 binary（GLB）。
无索引、每三角形独立顶点 + 面法线，单一材质——对讨论期的
盒体/圆柱组合预览足够，且实现简单可靠。

供 cad_preview_build 在 OCP 不可用时也能产出画布可渲染的 GLB；
若上游 OCCT 服务可用，其产物优先级更高（真实 B-Rep 细分）。
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

Point3 = tuple[float, float, float]
Triangle = tuple[Point3, Point3, Point3]

# 默认基色（线性空间近似的中性灰蓝，与画布卡片底色区分）
_DEFAULT_COLOR = (0.58, 0.64, 0.72, 1.0)


def _face_normal(triangle: Triangle) -> Point3:
    ax, ay, az = triangle[0]
    bx, by, bz = triangle[1]
    cx, cy, cz = triangle[2]
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / length, ny / length, nz / length


def write_glb(
    path: Path,
    name: str,
    triangles: list[Triangle],
    color: tuple[float, float, float, float] = _DEFAULT_COLOR,
) -> dict[str, Any]:
    """把三角面片写出为 GLB，返回包围盒信息。

    Args:
        path: 目标 .glb 路径（父目录需已存在）
        name: glTF asset 名称
        triangles: 三角面片列表（米/毫米单位原样写入，由查看器缩放）
        color: 基色 RGBA（线性空间 0-1）

    Returns:
        dict: {"min": [x,y,z], "max": [x,y,z], "triangles": int}
    """
    positions: list[float] = []
    normals: list[float] = []
    bounds_min = [math.inf, math.inf, math.inf]
    bounds_max = [-math.inf, -math.inf, -math.inf]
    for triangle in triangles:
        nx, ny, nz = _face_normal(triangle)
        for point in triangle:
            positions.extend(point)
            normals.extend((nx, ny, nz))
            for axis in range(3):
                bounds_min[axis] = min(bounds_min[axis], point[axis])
                bounds_max[axis] = max(bounds_max[axis], point[axis])
    if not positions:
        bounds_min, bounds_max = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]

    bin_positions = struct.pack(f"<{len(positions)}f", *positions)
    bin_normals = struct.pack(f"<{len(normals)}f", *normals)

    def _pad(data: bytes, alignment: int = 4, fill: int = 0x00) -> bytes:
        padding = (-len(data)) % alignment
        return data + bytes([fill]) * padding

    # bufferView 布局：POSITION + NORMAL 各一段，4 字节对齐
    view_positions = {"buffer": 0, "byteOffset": 0, "byteLength": len(bin_positions), "target": 34962}
    view_normals = {
        "buffer": 0,
        "byteOffset": len(bin_positions),
        "byteLength": len(bin_normals),
        "target": 34962,
    }
    vertex_count = len(positions) // 3
    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "illusion-forge cad workbench"},
        "scene": 0,
        "scenes": [{"nodes": [0], "name": name}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [
            {
                "name": name,
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1},
                        "material": 0,
                        "mode": 4,
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "workbench_preview",
                "pbrMetallicRoughness": {
                    "baseColorFactor": list(color),
                    "metallicFactor": 0.1,
                    "roughnessFactor": 0.55,
                },
                "doubleSided": True,
            }
        ],
        "buffers": [{"byteLength": len(bin_positions) + len(bin_normals)}],
        "bufferViews": [view_positions, view_normals],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": vertex_count,
                "type": "VEC3",
                "min": bounds_min,
                "max": bounds_max,
            },
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": vertex_count,
                "type": "VEC3",
            },
        ],
    }

    json_bytes = _pad(json.dumps(gltf, ensure_ascii=False).encode("utf-8"), fill=0x20)
    bin_bytes = _pad(bin_positions + bin_normals)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)

    path.write_bytes(
        struct.pack("<III", 0x46546C67, 2, total)  # magic "glTF", version, length
        + struct.pack("<II", len(json_bytes), 0x4E4F534A)  # JSON chunk ("JSON")
        + json_bytes
        + struct.pack("<II", len(bin_bytes), 0x004E4942)  # BIN chunk ("BIN\0")
        + bin_bytes
    )
    return {
        "min": [round(v, 6) for v in bounds_min],
        "max": [round(v, 6) for v in bounds_max],
        "triangles": len(triangles),
    }
