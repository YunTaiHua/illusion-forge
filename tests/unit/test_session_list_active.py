"""测试各 SessionStore 的 list_active 方法"""
from __future__ import annotations

import json
import time
from pathlib import Path

from illusion_forge.channels.base import SessionInfo


def _write_session(path: Path, *, user_id: str, chat_type: str = "dm",
                   messages: list | None = None, model: str = "") -> None:
    """写入一个假会话文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "session_id": "test123",
        "messages": messages or [],
        "user_id": user_id,
        "chat_type": chat_type,
        "model": model,
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_feishu_list_active_returns_recent_sessions(tmp_path: Path) -> None:
    from illusion_forge.channels.feishu.session_map import FeishuSessionStore
    store = FeishuSessionStore(data_dir=tmp_path)
    # 写入两个会话文件（key 格式 u:user_id 或 g:chat_id:user_id）
    _write_session(tmp_path / "u_ou_file1.json", user_id="ou_file1", chat_type="dm")
    time.sleep(0.05)
    _write_session(tmp_path / "g_oc_group1_ou_user2.json",
                   user_id="ou_user2", chat_type="group")
    sessions = store.list_active(limit=5)
    assert len(sessions) == 2
    # 较新的文件应排在前面
    assert sessions[0].chat_type == "group"
    assert sessions[0].chat_id == "oc_group1"  # 群聊 chat_id 不应含 user_id 部分
    assert isinstance(sessions[0], SessionInfo)


def test_feishu_list_active_respects_limit(tmp_path: Path) -> None:
    from illusion_forge.channels.feishu.session_map import FeishuSessionStore
    store = FeishuSessionStore(data_dir=tmp_path)
    for i in range(7):
        _write_session(tmp_path / f"u_ou_user{i}.json", user_id=f"ou_user{i}")
        time.sleep(0.01)
    sessions = store.list_active(limit=3)
    assert len(sessions) == 3


def test_feishu_list_active_empty_dir(tmp_path: Path) -> None:
    from illusion_forge.channels.feishu.session_map import FeishuSessionStore
    store = FeishuSessionStore(data_dir=tmp_path)
    assert store.list_active() == []


def test_qq_list_active(tmp_path: Path) -> None:
    from illusion_forge.channels.qq.session_map import QQSessionStore
    store = QQSessionStore(data_dir=tmp_path)
    _write_session(tmp_path / "openid_user1.json", user_id="openid_user1")
    sessions = store.list_active(limit=5)
    assert len(sessions) == 1
    assert sessions[0].chat_id  # QQ 的 chat_id 即文件名（去 .json）


def test_weixin_list_active(tmp_path: Path) -> None:
    from illusion_forge.channels.weixin.session_map import WeixinSessionStore
    store = WeixinSessionStore(data_dir=tmp_path)
    _write_session(tmp_path / "u_wxid_user1.json", user_id="wxid_user1")
    sessions = store.list_active(limit=5)
    assert len(sessions) == 1
    assert sessions[0].chat_id  # 微信 chat_id 即 user_id（去 u_ 前缀）
