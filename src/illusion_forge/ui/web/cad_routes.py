"""CAD 工作台 REST 路由：产物文件服务。

画布上的 3D 预览卡（GLB）与快照卡需要以 URL 加载二进制产物
（WebSocket 的 web_read_file 拒绝二进制内容），本模块提供受限的
``GET /api/cad/artifact?path=...``：

    - 仅允许服务 ``<工作区>/.illusion/cad_artifacts`` 目录树内（以及
      settings.workbench.artifacts_dir 指定目录内）的文件，拒绝穿越；
    - 认证由全局 _AuthMiddleware 统一处理（cookie/bearer/query token）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

log = logging.getLogger(__name__)

# 产物扩展名 → MIME（GLB 无系统注册表项，显式指定）
_MEDIA_TYPES = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".step": "application/step",
    ".stp": "application/step",
    ".iges": "application/iges",
    ".igs": "application/iges",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


def _allowed_artifact_roots() -> list[Path]:
    """收集允许服务的产物根目录（默认工作区 + 已注册工作区 + 自定义目录）。"""
    roots: list[Path] = []
    try:
        from illusion_forge.services import workspace_registry
        from illusion_forge.services.workspace_registry import list_registered_workspaces

        candidates: list[Any] = [workspace_registry.get_default_workspace()]
        for entry in list_registered_workspaces():
            path = getattr(entry, "path", None)
            if path:
                candidates.append(path)
    except Exception:
        log.debug("收集工作区目录失败，仅使用默认工作区", exc_info=True)
        from illusion_forge.services import workspace_registry

        candidates = [workspace_registry.get_default_workspace()]
    for candidate in candidates:
        if candidate:
            roots.append(Path(str(candidate)) / ".illusion" / "cad_artifacts")
    # 自定义产物目录（settings.workbench.artifacts_dir）
    try:
        from illusion_forge.config.settings import load_settings

        custom = load_settings().workbench.artifacts_dir
        if custom:
            roots.append(Path(custom))
    except Exception:
        log.debug("读取自定义产物目录失败", exc_info=True)
    normalized: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved not in normalized:
            normalized.append(resolved)
    return normalized


def register_cad_routes(app: FastAPI) -> None:
    """注册 CAD 产物服务路由（在 StaticFiles mount 之前调用）。"""

    @app.get("/api/cad/artifact")
    async def get_cad_artifact(path: str = "") -> FileResponse:
        """按绝对路径返回 CAD 产物文件（限 artifacts 目录树内）。"""
        raw = (path or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="缺少 path 参数")
        target = Path(raw)
        try:
            resolved = target.resolve()
        except OSError as exc:
            raise HTTPException(status_code=400, detail="无效的路径") from exc
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="产物文件不存在")
        allowed = False
        for root in _allowed_artifact_roots():
            try:
                resolved.relative_to(root)
                allowed = True
                break
            except ValueError:
                continue
        if not allowed:
            raise HTTPException(status_code=403, detail="路径不在 CAD 产物目录内")
        media_type = _MEDIA_TYPES.get(resolved.suffix.lower(), "application/octet-stream")
        return FileResponse(resolved, media_type=media_type)
