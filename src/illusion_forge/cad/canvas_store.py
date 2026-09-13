"""画布工作台文档存储
==================

agent 与用户共享的画布真源：节点/边 CRUD、按会话隔离持久化、
变更广播。文档形态与 React Flow 受控数据对齐。

主要组件：
    - CanvasStore: 单画布存储（线程安全，按 工作区×会话 惰性单例）
    - subscribe_canvas_broadcast: 变更广播订阅（WebSocket 推送用）
    - for_session / for_cwd: 按会话或工作区获取存储实例

文档结构：
    {
      "version": 1, "revision": 7, "updated_at": "...",
      "nodes": [{"id", "kind", "title", "body", "data", "position"}],
      "edges": [{"id", "source", "target", "label"}]
    }
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

from illusion_forge.utils.atomic_write import atomic_write_text

log = logging.getLogger(__name__)

# 画布节点种类（前端 WorkbenchNode 据此渲染卡片）
NODE_KINDS = {"requirement", "variant", "preview", "snapshot", "spec", "note"}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def cwd_key(cwd: str | Path) -> str:
    """返回工作区目录的索引键（规范化 + 大小写归一，Windows 兼容）。"""
    return os.path.normcase(os.path.normpath(str(cwd)))


def artifacts_root(cwd: str | Path) -> Path:
    """返回工作区的 CAD 产物根目录。"""
    return Path(cwd) / ".illusion" / "cad_artifacts"


def _safe_session_id(session_id: str | None) -> str:
    """会话 ID 清洗为安全的文件名主干（非法/空值回落 default）。"""
    import re as _re

    raw = str(session_id or "").strip()
    cleaned = _re.sub(r"[^A-Za-z0-9_-]", "", raw)[:64]
    return cleaned or "default"


# === 模块级广播器：CanvasStore 实例按工作区惰性创建，主机订阅此处 ===
# 回调签名：callback(doc_dict, cwd) -> None（同步调用；主机内部自行调度异步任务。
# cwd 为画布所属工作区目录，供前端按归属过滤多工作区串档）
_subscribers: list[Callable[[dict[str, Any], str], None]] = []
_subscriber_lock = threading.Lock()


def subscribe_canvas_broadcast(callback: Callable[[dict[str, Any], str], None]) -> Callable[[], None]:
    """订阅画布变更广播，返回取消订阅函数。"""
    with _subscriber_lock:
        _subscribers.append(callback)

    def _unsubscribe() -> None:
        with _subscriber_lock:
            try:
                _subscribers.remove(callback)
            except ValueError:
                pass

    return _unsubscribe


def _broadcast(doc: dict[str, Any], cwd: str) -> None:
    with _subscriber_lock:
        callbacks = list(_subscribers)
    for callback in callbacks:
        try:
            callback(doc, cwd)
        except Exception:
            log.exception("画布变更广播回调异常")


class CanvasStore:
    """单个工作区的画布文档存储（线程安全，惰性单例）。"""

    _instances: ClassVar[dict[str, CanvasStore]] = {}
    _instance_lock = threading.Lock()

    def __init__(self, board_path: Path, cwd: str | Path) -> None:
        self._path = board_path
        self._cwd = str(cwd)
        self._lock = threading.RLock()
        self._doc: dict[str, Any] = self._load()

    @classmethod
    def for_session(cls, cwd: str | Path, session_id: str | None) -> CanvasStore:
        """按（工作区, 会话）返回画布存储单例——画布按会话隔离。

        Args:
            cwd: 工作区目录
            session_id: 会话 ID；空/非法值回落到 "default" 画布（兼容旧数据）
        """
        safe = _safe_session_id(session_id)
        key = cwd_key(cwd) + "::" + safe
        with cls._instance_lock:
            store = cls._instances.get(key)
            if store is None:
                board_dir = artifacts_root(cwd) / "canvas"
                store = cls(board_dir / f"{safe}.json", cwd)
                cls._instances[key] = store
            return store

    @classmethod
    def for_cwd(cls, cwd: str | Path) -> CanvasStore:
        """兼容入口：工作区默认画布（等价 for_session(cwd, None)）。"""
        return cls.for_session(cwd, None)

    # === 持久化 ===

    def _load(self) -> dict[str, Any]:
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("nodes"), list):
                raw.setdefault("edges", [])
                raw.setdefault("revision", 0)
                raw.setdefault("version", 1)
                return raw
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.warning("画布文档读取失败，使用空白画布: %s", self._path)
        return {"version": 1, "revision": 0, "updated_at": "", "nodes": [], "edges": []}

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self._path,
            json.dumps(self._doc, ensure_ascii=False, indent=2) + "\n",
        )

    def _touch(self) -> None:
        self._doc["revision"] = int(self._doc.get("revision", 0)) + 1
        self._doc["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    # === 读取 / 前端整板替换 ===

    def get_doc(self) -> dict[str, Any]:
        """返回画布文档快照（深拷贝）。

        每次从磁盘重读：服务端每次变更都即时落盘（磁盘即权威），
        重读使 CLI 等跨进程对 board.json 的修改对本进程可见——否则
        web_canvas_get / 聚焦重取拿到的会是陈旧的内存缓存。
        """
        with self._lock:
            self._doc = self._load()
            return copy.deepcopy(self._doc)

    def replace_from_frontend(self, payload: Any) -> dict[str, Any]:
        """接受前端的整板编辑（受控 React Flow 数据），规范化后持久化并广播。

        前端发送 {nodes, edges}；节点 id/position/kind/title/body/data 与
        边 id/source/target/label 之外的字段被丢弃——这是刻意的严格契约：
        节点级扩展一律放进 ``data`` 字典（它是透传的扩展点，lineage 的
        model_path/params 等都存这里），顶层 schema 变更需要同步前后端。
        用户编辑与 agent 工具操作共用同一真源，revision 单调递增。
        """
        if not isinstance(payload, dict):
            raise TypeError("画布更新载荷必须是 object")
        raw_nodes = payload.get("nodes")
        raw_edges = payload.get("edges")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise TypeError("画布更新载荷必须包含 nodes[] 与 edges[]")
        with self._lock:
            nodes: list[dict[str, Any]] = []
            for raw in raw_nodes:
                if not isinstance(raw, dict) or not str(raw.get("id") or "").strip():
                    continue
                node_data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
                kind = str(raw.get("kind") or "note")
                if kind not in NODE_KINDS:
                    kind = "note"
                raw_position = raw.get("position")
                position = raw_position if isinstance(raw_position, dict) else {}
                nodes.append(
                    {
                        "id": str(raw["id"]),
                        "kind": kind,
                        "title": str(raw.get("title") or ""),
                        "body": str(raw.get("body") or ""),
                        "data": node_data,
                        "position": {
                            "x": float(position.get("x") or 0),
                            "y": float(position.get("y") or 0),
                        },
                        "created_at": str(raw.get("created_at") or ""),
                    }
                )
            known_ids = {node["id"] for node in nodes}
            edges: list[dict[str, Any]] = []
            for raw in raw_edges:
                if not isinstance(raw, dict):
                    continue
                source, target = str(raw.get("source") or ""), str(raw.get("target") or "")
                if source in known_ids and target in known_ids and source != target:
                    edges.append(
                        {
                            "id": str(raw.get("id") or _new_id("e")),
                            "source": source,
                            "target": target,
                            "label": str(raw.get("label") or ""),
                        }
                    )
            self._doc["nodes"] = nodes
            self._doc["edges"] = edges
            self._touch()
            self._persist()
            snapshot = copy.deepcopy(self._doc)
        _broadcast(snapshot, self._cwd)
        return snapshot

    # === agent 结构化操作 ===

    def apply_op(self, op: Any) -> dict[str, Any]:
        """执行单个 agent 画布操作，返回更新后的文档快照。

        支持的 action：add_node / update_node / remove_node /
        add_edge / remove_edge / clear。
        """
        if not isinstance(op, dict):
            raise TypeError("画布操作必须是 object")
        action = str(op.get("action") or "")
        with self._lock:
            handler = {
                "add_node": self._op_add_node,
                "update_node": self._op_update_node,
                "remove_node": self._op_remove_node,
                "add_edge": self._op_add_edge,
                "remove_edge": self._op_remove_edge,
                "clear": self._op_clear,
            }.get(action)
            if handler is None:
                raise ValueError(f"不支持的画布操作: {action!r}")
            handler(op)
            self._touch()
            self._persist()
            snapshot = copy.deepcopy(self._doc)
        _broadcast(snapshot, self._cwd)
        return snapshot

    def _op_add_node(self, op: dict[str, Any]) -> None:
        kind = str(op.get("kind") or "note")
        if kind not in NODE_KINDS:
            raise ValueError(f"未知节点类型: {kind!r}（可选: {', '.join(sorted(NODE_KINDS))}）")
        node_id = str(op.get("node_id") or "") or _new_id("n")
        if any(node["id"] == node_id for node in self._doc["nodes"]):
            raise ValueError(f"节点 id 已存在: {node_id}")
        x, y = op.get("x"), op.get("y")
        if x is None or y is None:
            # 自动网格排布：按现有节点数错开，避免叠放
            index = len(self._doc["nodes"])
            x, y = 40 + (index % 5) * 330, 40 + (index // 5) * 250
        node = {
            "id": node_id,
            "kind": kind,
            "title": str(op.get("title") or ""),
            "body": str(op.get("body") or ""),
            "data": op.get("data") if isinstance(op.get("data"), dict) else {},
            "position": {"x": float(x), "y": float(y)},
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self._doc["nodes"].append(node)
        # connect_to: 创建与既有节点的连线（方案关联需求、预览关联方案等）
        for target in op.get("connect_to") or []:
            target_id = str(target)
            if target_id != node_id and any(n["id"] == target_id for n in self._doc["nodes"]):
                self._doc["edges"].append(
                    {"id": _new_id("e"), "source": node_id, "target": target_id,
                     "label": str(op.get("edge_label") or "")}
                )

    def _op_update_node(self, op: dict[str, Any]) -> None:
        node_id = str(op.get("node_id") or "")
        node = next((n for n in self._doc["nodes"] if n["id"] == node_id), None)
        if node is None:
            raise ValueError(f"节点不存在: {node_id}")
        for key in ("title", "body"):
            if op.get(key) is not None:
                node[key] = str(op[key])
        if isinstance(op.get("data"), dict):
            node["data"] = op["data"]
        if op.get("x") is not None and op.get("y") is not None:
            node["position"] = {"x": float(op["x"]), "y": float(op["y"])}

    def _op_remove_node(self, op: dict[str, Any]) -> None:
        node_id = str(op.get("node_id") or "")
        before = len(self._doc["nodes"])
        self._doc["nodes"] = [n for n in self._doc["nodes"] if n["id"] != node_id]
        if len(self._doc["nodes"]) == before:
            raise ValueError(f"节点不存在: {node_id}")
        self._doc["edges"] = [
            e for e in self._doc["edges"] if e["source"] != node_id and e["target"] != node_id
        ]

    def _op_add_edge(self, op: dict[str, Any]) -> None:
        source, target = str(op.get("source") or ""), str(op.get("target") or "")
        ids = {n["id"] for n in self._doc["nodes"]}
        if source not in ids or target not in ids or source == target:
            raise ValueError(f"连线端点无效: {source} -> {target}")
        self._doc["edges"].append(
            {"id": _new_id("e"), "source": source, "target": target,
             "label": str(op.get("label") or "")}
        )

    def _op_remove_edge(self, op: dict[str, Any]) -> None:
        edge_id = str(op.get("edge_id") or "")
        before = len(self._doc["edges"])
        self._doc["edges"] = [e for e in self._doc["edges"] if e["id"] != edge_id]
        if len(self._doc["edges"]) == before:
            raise ValueError(f"连线不存在: {edge_id}")

    def _op_clear(self, _op: dict[str, Any]) -> None:
        self._doc["nodes"] = []
        self._doc["edges"] = []
