"""文件历史快照模块
================

本模块提供基于文件复制的快照管理，用于支持 /rewind 指令的文件回退。

rewind 时从备份恢复。不依赖 git，可跟踪任意路径的文件。

存储位置：~/.illusion/data/file-history/{session_id}/{sha256(path)[:16]}@v{N}

主要函数：
    - track_edit: 在工具修改文件前备份（copy-on-write）
    - make_snapshot: 创建快照边界（每条用户消息一次）
    - rewind_to: 回退到指定快照，恢复文件

使用示例：
    >>> from illusion_forge.services.file_history import FileHistoryState
    >>> state = FileHistoryState(session_id="abc123", cwd="/project")
    >>> track_edit(state, "/project/file.py")
    >>> make_snapshot(state, "msg-uuid-1", 0)
    >>> rewind_to(state, 0)
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from illusion_forge.config.paths import get_config_dir, resolve_relative_path
from illusion_forge.services.session_storage import (
    _validate_session_id,
    get_project_session_dir_no_create,
)
from illusion_forge.utils.atomic_write import atomic_write_text


@dataclass
class FileBackup:
    """单个文件的备份记录。"""
    backup_name: str | None  # 备份文件名，None 表示文件当时不存在
    version: int


@dataclass
class FileSnapshot:
    """一个快照：关联到一条用户消息，包含所有跟踪文件的备份映射。"""
    message_id: str
    turn_index: int = 0  # 轮次索引（0-based）
    tracked_backups: dict[str, FileBackup] = field(default_factory=dict)
    # Task 2 将在 make_snapshot 中传入此字段；Task 1 仅用于 save/load 序列化
    checkpoint_id: int = 0


@dataclass
class FileHistoryState:
    """文件历史状态。"""
    session_id: str
    cwd: str
    snapshots: list[FileSnapshot] = field(default_factory=list)
    tracked_files: set[str] = field(default_factory=set)
    _turn_counter: int = 0  # 内部轮次计数器
    # 会话数据目录（由 CheckpointStore 持有）。非 None 时 file_history.json
    # 的读写以它为准，不再用 cwd+session_id 重算路径，保证与 context.jsonl /
    # meta.json 同目录（会话目录唯一权威原则）。
    session_dir: Path | None = None


def _backup_dir(session_id: str) -> Path:
    """返回备份存储目录。"""
    return get_config_dir() / "file-history" / session_id


def _backup_name(file_path: str, version: int = 1) -> str:
    """生成备份文件名：sha256(路径@vN)[:16]。不同版本生成不同文件名。"""
    return sha256(f"{file_path}@v{version}".encode()).hexdigest()[:16]


def _backup_path(session_id: str, backup_name: str) -> Path:
    """返回备份文件的完整路径。"""
    return _backup_dir(session_id) / backup_name


def _state_path(cwd: str, session_id: str, session_dir: Path | None = None) -> Path:
    """返回 file_history.json 路径（不创建目录）。

    位于会话目录下，与 meta.json / context.jsonl 同目录，
    生命周期对齐：会话删除时随目录一并清理。

    session_dir 由 CheckpointStore 持有（唯一权威）；为 None 时
    退化为 cwd+session_id 计算（兼容无 store 的只读场景）。

    Args:
        cwd: 项目工作目录
        session_id: 会话 ID
        session_dir: 会话数据目录（store.session_dir），可选

    Returns:
        Path: file_history.json 完整路径
    """
    if session_dir is not None:
        return session_dir / "file_history.json"
    _validate_session_id(session_id)
    project_dir = get_project_session_dir_no_create(cwd) / session_id
    return project_dir / "file_history.json"


def track_edit(state: FileHistoryState, file_path: str) -> None:
    """在工具修改文件前备份（copy-on-write）。

    如果文件在当前快照中已被跟踪，跳过。否则：
    - 文件存在：复制到备份目录
    - 文件不存在：记录 None（标记为"文件当时不存在"）

    Args:
        state: 文件历史状态
        file_path: 即将被修改的文件路径
    """
    abs_path = str(resolve_relative_path(Path(state.cwd), file_path))
    tracking_key = abs_path  # 使用绝对路径作为 key

    # 检查是否已在当前快照中跟踪
    if state.snapshots:
        current = state.snapshots[-1]
        if tracking_key in current.tracked_backups:
            return  # 已跟踪，跳过

    # 确定版本号：查找最近快照中此文件的备份版本
    version = 1
    for snap in reversed(state.snapshots):
        if tracking_key in snap.tracked_backups:
            version = snap.tracked_backups[tracking_key].version + 1
            break

    # 创建备份
    bname = _backup_name(abs_path, version)
    bpath = _backup_path(state.session_id, bname)

    if Path(abs_path).exists():
        # 文件存在：复制备份
        bpath.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(abs_path, bpath)
        backup = FileBackup(backup_name=bname, version=version)
    else:
        # 文件不存在（新文件）
        backup = FileBackup(backup_name=None, version=version)

    # 记录到当前快照
    if state.snapshots:
        state.snapshots[-1].tracked_backups[tracking_key] = backup

    state.tracked_files.add(tracking_key)
    save(state)


def make_snapshot(state: FileHistoryState, message_id: str, checkpoint_id: int) -> None:
    """创建快照边界。

    在用户发送消息时调用，为后续的工具编辑创建新的跟踪空间。

    Args:
        state: 文件历史状态
        message_id: 关联的消息 ID
        checkpoint_id: 对应的 checkpoint id（用于 rewind 精确对应）
    """
    snapshot = FileSnapshot(
        message_id=message_id,
        turn_index=state._turn_counter,
        checkpoint_id=checkpoint_id,
    )
    state._turn_counter += 1
    state.snapshots.append(snapshot)
    # 最多保留 50 个快照
    if len(state.snapshots) > 50:
        evicted = state.snapshots[:-50]
        state.snapshots = state.snapshots[-50:]
        # 清理被驱逐快照的备份文件
        _cleanup_evicted(state, evicted)
    save(state)


def rewind_to(state: FileHistoryState, target_checkpoint_id: int) -> list[str]:
    """撤销 checkpoint_id >= target_checkpoint_id 的所有快照的文件修改。

    使用 checkpoint_id 而非位置定位，确保 /rewind code 后 /rewind both
    不会错位。

    Args:
        state: 文件历史状态
        target_checkpoint_id: 目标 checkpoint id（>= 该值的快照被撤销）

    Returns:
        list[str]: 被恢复的文件路径列表
    """
    removed = [s for s in state.snapshots if s.checkpoint_id >= target_checkpoint_id]
    if not removed:
        return []

    # 收集被撤销范围内所有快照中跟踪的文件
    files_to_restore: set[str] = set()
    for snap in removed:
        files_to_restore.update(snap.tracked_backups.keys())

    changed: list[str] = []
    for tracking_key in files_to_restore:
        # 在被撤销的快照中找到该文件最早的备份（即修改前的状态）
        backup = None
        for snap in removed:
            if tracking_key in snap.tracked_backups:
                backup = snap.tracked_backups[tracking_key]
                break

        if backup is None:
            continue

        if backup.backup_name is None:
            # 文件当时不存在：删除
            p = Path(tracking_key)
            if p.exists():
                p.unlink()
                changed.append(tracking_key)
        else:
            # 从备份恢复（备份内容 = 工具执行前的状态）
            bpath = _backup_path(state.session_id, backup.backup_name)
            if bpath.exists():
                p = Path(tracking_key)
                current_content = p.read_bytes() if p.exists() else None
                backup_content = bpath.read_bytes()
                if current_content != backup_content:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(bpath, tracking_key)
                    changed.append(tracking_key)

    # 移除目标快照及之后的所有快照
    state.snapshots = [s for s in state.snapshots if s.checkpoint_id < target_checkpoint_id]
    _cleanup_evicted(state, removed)

    # 重置轮次计数器，保持后续快照的 turn_index 连续
    state._turn_counter = len(state.snapshots)
    save(state)

    return changed


def _find_first_backup(state: FileHistoryState, tracking_key: str) -> FileBackup | None:
    """找到文件的最早备份。"""
    for snap in state.snapshots:
        backup = snap.tracked_backups.get(tracking_key)
        if backup is not None:
            return backup
    return None


def cleanup_file_history(session_id: str) -> None:
    """删除指定会话的文件历史目录。

    防御性校验 session_id 合法性：拒绝路径分隔符/``..``/``~``，
    防止非法 ID 触发路径穿越删除到 file-history 目录之外。
    """
    if not session_id or ".." in session_id or "/" in session_id or "\\" in session_id or "~" in session_id:
        return
    d = _backup_dir(session_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def cleanup_all_file_histories() -> int:
    """删除所有文件历史目录，返回删除的目录数。"""
    base = get_config_dir() / "file-history"
    if not base.exists():
        return 0
    count = 0
    for child in base.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            count += 1
    # 如果 base 为空，删除它
    try:
        base.rmdir()
    except OSError:
        pass
    return count


def _cleanup_evicted(state: FileHistoryState, evicted: list[FileSnapshot]) -> None:
    """清理被驱逐快照的孤立备份文件。"""
    # 收集仍被引用的备份名
    still_referenced: set[str] = set()
    for snap in state.snapshots:
        for backup in snap.tracked_backups.values():
            if backup.backup_name:
                still_referenced.add(backup.backup_name)

    # 删除不再被引用的备份
    for snap in evicted:
        for backup in snap.tracked_backups.values():
            if backup.backup_name and backup.backup_name not in still_referenced:
                bpath = _backup_path(state.session_id, backup.backup_name)
                try:
                    bpath.unlink(missing_ok=True)
                except OSError:
                    pass


def save(state: FileHistoryState) -> None:
    """序列化状态为 JSON，原子写入 file_history.json。

    写前 mkdir(parents=True, exist_ok=True)。使用 atomic_write_text
    保证崩溃安全。

    Args:
        state: 文件历史状态
    """
    payload = {
        "version": 1,
        "session_id": state.session_id,
        "cwd": state.cwd,
        "turn_counter": state._turn_counter,
        "tracked_files": sorted(state.tracked_files),
        "snapshots": [
            {
                "message_id": snap.message_id,
                "turn_index": snap.turn_index,
                "checkpoint_id": snap.checkpoint_id,
                "tracked_backups": {
                    k: {"backup_name": b.backup_name, "version": b.version}
                    for k, b in snap.tracked_backups.items()
                },
            }
            for snap in state.snapshots
        ],
    }
    path = _state_path(state.cwd, state.session_id, state.session_dir)
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def load(
    cwd: str,
    session_id: str,
    checkpoint_count: int | None = None,
    session_dir: Path | None = None,
) -> FileHistoryState | None:
    """从 file_history.json 加载状态。

    文件不存在或损坏返回 None（降级为无历史）。旧格式 snapshot 缺失
    checkpoint_id 字段时整个返回 None（保守降级）。

    Args:
        cwd: 项目工作目录
        session_id: 会话 ID
        checkpoint_count: 当前 CheckpointStore.next_checkpoint_id，
            用于崩溃恢复对齐。None 时不做对齐（懒初始化场景）。
        session_dir: 会话数据目录（store.session_dir），可选。
            传入后 file_history.json 以它定位，且加载出的 state
            会持有该 session_dir，后续 save 写入同一目录。

    Returns:
        FileHistoryState | None: 加载的状态或 None
    """
    path = _state_path(cwd, session_id, session_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # 校验必需字段
    if not isinstance(data, dict) or "snapshots" not in data:
        return None

    snapshots: list[FileSnapshot] = []
    for snap_data in data.get("snapshots", []):
        # 旧格式兼容：缺失 checkpoint_id 整体降级
        if "checkpoint_id" not in snap_data:
            return None
        tracked_backups: dict[str, FileBackup] = {}
        for k, b in snap_data.get("tracked_backups", {}).items():
            tracked_backups[k] = FileBackup(
                backup_name=b.get("backup_name"),
                version=b.get("version", 1),
            )
        snapshots.append(
            FileSnapshot(
                message_id=snap_data.get("message_id", ""),
                turn_index=snap_data.get("turn_index", 0),
                tracked_backups=tracked_backups,
                checkpoint_id=snap_data.get("checkpoint_id", 0),
            )
        )

    state = FileHistoryState(
        session_id=data.get("session_id", session_id),
        cwd=data.get("cwd", cwd),
        snapshots=snapshots,
        tracked_files=set(data.get("tracked_files", [])),
        _turn_counter=data.get("turn_counter", len(snapshots)),
        session_dir=session_dir,
    )

    # 崩溃恢复对齐：丢弃 checkpoint_id >= checkpoint_count 的 snapshot
    if checkpoint_count is not None:
        original_len = len(state.snapshots)
        state.snapshots = [
            s for s in state.snapshots
            if s.checkpoint_id < checkpoint_count
        ]
        if len(state.snapshots) != original_len:
            state._turn_counter = len(state.snapshots)
            save(state)

    return state
