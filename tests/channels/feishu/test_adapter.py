"""飞书适配器准入控制测试。"""
from __future__ import annotations

import pytest

from illusion_forge.channels.base import InboundMessage
from illusion_forge.channels.config import FeishuChannelConfig, FeishuGroupPolicy

lark_oapi = pytest.importorskip("lark_oapi")
from illusion_forge.channels.feishu.adapter import FeishuChannel


def _channel(allow_bots=False, require_mention=True, policy_mode="open",
             allowlist=None, blacklist=None, admin_list=None, bot_id="ou_bot"):
    """构造 FeishuChannel 实例（仅测准入逻辑，不连接）。"""
    cfg = FeishuChannelConfig(
        enabled=True, app_id="cli", app_secret="s",
        allow_bots=allow_bots, require_mention=require_mention,
        group_policy=FeishuGroupPolicy(
            mode=policy_mode, allowlist=allowlist or [],
            blacklist=blacklist or [], admin_list=admin_list or [],
        ),
    )
    ch = FeishuChannel.__new__(FeishuChannel)  # 跳过 __init__ 避免连接
    ch.config = cfg
    ch._bot_open_id = bot_id  # 模拟已 hydrate 的 bot ID
    return ch


def _msg(user_id="ou_user", chat_type="dm", is_bot=False, text="hi",
         chat_id="ou_user", mentioned_bot=False):
    """构造入站消息及 @bot 标志。"""
    msg = InboundMessage(
        text=text, chat_id=chat_id, chat_type=chat_type,
        user_id=user_id, user_name="u", message_id="om_1", is_bot=is_bot,
    )
    return msg, mentioned_bot


def test_admit_self_echo_rejected():
    """自回显（发送者是 bot 自身）被拒。"""
    ch = _channel()
    msg, _ = _msg(user_id="ou_bot")  # 发送者 == bot
    assert ch._admit(msg, mentioned_bot=False) is False


def test_admit_other_bot_rejected_when_disallowed():
    """allow_bots=False 时其他机器人被拒。"""
    ch = _channel(allow_bots=False)
    msg, _ = _msg(user_id="ou_other_bot", is_bot=True)
    assert ch._admit(msg, mentioned_bot=False) is False


def test_admit_other_bot_allowed_when_enabled():
    """allow_bots=True 时其他机器人放行。"""
    ch = _channel(allow_bots=True)
    msg, _ = _msg(user_id="ou_other_bot", is_bot=True)
    assert ch._admit(msg, mentioned_bot=False) is True


def test_admit_dm_always_allowed():
    """私聊（非 bot 非 self）放行。"""
    ch = _channel()
    msg, _ = _msg(user_id="ou_user", chat_type="dm")
    assert ch._admit(msg, mentioned_bot=False) is True


def test_admit_group_require_mention_rejected_without_mention():
    """群组 require_mention=True 但未 @bot 时被拒。"""
    ch = _channel(require_mention=True)
    msg, _ = _msg(user_id="ou_user", chat_type="group", chat_id="oc_room")
    assert ch._admit(msg, mentioned_bot=False) is False


def test_admit_group_require_mention_allowed_with_mention():
    """群组 require_mention=True 且 @bot 时放行。"""
    ch = _channel(require_mention=True)
    msg, _ = _msg(user_id="ou_user", chat_type="group", chat_id="oc_room")
    assert ch._admit(msg, mentioned_bot=True) is True


def test_admit_group_policy_disabled():
    """群组策略 mode=disabled 全拒。"""
    ch = _channel(policy_mode="disabled")
    msg, _ = _msg(user_id="ou_user", chat_type="group", chat_id="oc_room")
    assert ch._admit(msg, mentioned_bot=True) is False


def test_admit_group_policy_allowlist():
    """群组策略 mode=allowlist 仅白名单放行。"""
    ch = _channel(policy_mode="allowlist", allowlist=["oc_allowed"])
    msg_ok, _ = _msg(user_id="ou_user", chat_type="group", chat_id="oc_allowed")
    msg_no, _ = _msg(user_id="ou_user", chat_type="group", chat_id="oc_blocked")
    assert ch._admit(msg_ok, mentioned_bot=True) is True
    assert ch._admit(msg_no, mentioned_bot=True) is False


def test_admit_group_policy_blacklist():
    """群组策略 mode=blacklist 黑名单外放行。"""
    ch = _channel(policy_mode="blacklist", blacklist=["oc_blocked"])
    msg_ok, _ = _msg(user_id="ou_user", chat_type="group", chat_id="oc_ok")
    msg_no, _ = _msg(user_id="ou_user", chat_type="group", chat_id="oc_blocked")
    assert ch._admit(msg_ok, mentioned_bot=True) is True
    assert ch._admit(msg_no, mentioned_bot=True) is False


def test_admit_group_admin_always_allowed():
    """管理员 user_id 永远放行（即使群组策略禁止）。"""
    ch = _channel(policy_mode="disabled", admin_list=["ou_admin"])
    msg, _ = _msg(user_id="ou_admin", chat_type="group", chat_id="oc_room")
    assert ch._admit(msg, mentioned_bot=False) is True


def test_admit_dm_not_affected_by_group_policy():
    """私聊不受群组策略影响。"""
    ch = _channel(policy_mode="disabled")
    msg, _ = _msg(user_id="ou_user", chat_type="dm")
    assert ch._admit(msg, mentioned_bot=False) is True


def _make_real_event(chat_type="p2p", sender_open_id="ou_user",
                     sender_type="user", chat_id="ou_user",
                     content='{"text":"hello"}', mentions=None):
    """构造真实 lark-oapi 强类型事件对象（用于测 _normalize）。"""
    from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import (
        P2ImMessageReceiveV1,
    )

    msg_data = {
        "chat_id": chat_id,
        "chat_type": chat_type,
        "message_id": "om_test",
        "content": content,
    }
    if mentions is not None:
        msg_data["mentions"] = mentions
    event = P2ImMessageReceiveV1({"event": {"sender": {"sender_id": {"open_id": sender_open_id}, "sender_type": sender_type}, "message": msg_data}})
    return event


def test_normalize_real_event_dm_text():
    """_normalize 正确解析强类型 DM 文本事件。"""
    ch = _channel()
    event = _make_real_event(content='{"text":"你好"}')
    msg = ch._normalize(event)
    assert msg is not None
    assert msg.text == "你好"
    assert msg.chat_type == "dm"
    assert msg.user_id == "ou_user"
    assert msg.message_id == "om_test"
    assert msg.is_bot is False


def test_normalize_real_event_group():
    """_normalize 正确解析群组事件。"""
    ch = _channel()
    event = _make_real_event(chat_type="group", chat_id="oc_room")
    msg = ch._normalize(event)
    assert msg is not None
    assert msg.chat_type == "group"
    assert msg.chat_id == "oc_room"


def test_normalize_real_event_bot_sender():
    """_normalize 正确识别机器人发送者。"""
    ch = _channel()
    event = _make_real_event(sender_open_id="ou_other", sender_type="app")
    msg = ch._normalize(event)
    assert msg is not None
    assert msg.is_bot is True


def test_event_mentions_bot_with_real_event():
    """_event_mentions_bot 正确检测 @bot。"""
    ch = _channel(bot_id="ou_bot")
    # 不带 mentions
    event_no = _make_real_event()
    assert ch._event_mentions_bot(event_no) is False
    # 带 mentions（未 hydrate bot id 时，有 mention 即 True）
    ch._bot_open_id = ""
    mentions = [{"key": "@_user_1", "id": {"open_id": "ou_bot"}, "name": "bot"}]
    event_yes = _make_real_event(mentions=mentions)
    assert ch._event_mentions_bot(event_yes) is True
    # hydrate bot id 后精确匹配
    ch._bot_open_id = "ou_bot"
    assert ch._event_mentions_bot(event_yes) is True


# ─── 断网恢复修复测试：每连接 executor / 队列重建 / 禁用自动重连 ─────────────


def _new_channel() -> FeishuChannel:
    """构造未连接 FeishuChannel 实例（__new__ 跳过 __init__，手动补齐属性）。"""
    from illusion_forge.channels.feishu.adapter import FeishuChannel

    cfg = FeishuChannelConfig(
        enabled=True, app_id="cli_test", app_secret="s",
    )
    ch = FeishuChannel.__new__(FeishuChannel)
    ch.config = cfg
    ch._client = None
    ch._ws = None
    ch._queue = None
    ch._loop = None
    ch._bot_open_id = ""
    ch._stop_event = None
    ch._ws_future = None
    ch._ws_executor = None
    return ch


def _mock_connect(ch: FeishuChannel, fake_ws) -> None:
    """Mock 掉 build_lark_client / FeishuWSClient / _hydrate_bot_id 后执行 connect()。"""
    import asyncio
    from unittest import mock

    async def _do():
        with mock.patch(
            "illusion_forge.channels.feishu.messaging.build_lark_client",
            return_value=mock.Mock(),
        ), mock.patch(
            "illusion_forge.channels.feishu.ws_client.FeishuWSClient",
            return_value=fake_ws,
        ), mock.patch.object(ch, "_hydrate_bot_id", new=mock.AsyncMock()):
            await ch.connect()

    asyncio.run(_do())


def test_reconnect_rebuilds_queue():
    """shutdown() 关闭队列后，再次 connect() 重建队列，listen() 可重新使用。

    断网恢复的核心路径：watchdog 触发 shutdown 永久关闭队列后，
    _supervise 无退避重启 runner，connect() 必须重建队列，否则
    listen() 立即抛 QueueShutDown 导致无限快速重启。
    """
    import asyncio
    from unittest import mock

    ch = _new_channel()
    fake_ws = mock.Mock()
    _mock_connect(ch, fake_ws)

    queue1 = ch._queue
    assert queue1 is not None
    # 模拟 watchdog 触发 shutdown（永久关闭队列）
    asyncio.run(ch.shutdown())

    # 再次 connect（_supervise 重启路径）
    _mock_connect(ch, fake_ws)

    # 队列必须重建为全新实例，且未关闭（新队列 listen() 可正常阻塞等待）
    assert ch._queue is not queue1, "shutdown 后 connect() 必须重建入站队列"
    assert not getattr(ch._queue, "_shutdown", False)


def test_stop_disables_auto_reconnect():
    """FeishuWSClient.stop() 必须先禁用底层 lark 客户端自动重连。

    防止被 _supervise 放弃的旧客户端在网络恢复后自行重连，重读已被
    新连接覆盖的 lark 模块级共享 loop，破坏新连接。
    """
    from unittest import mock

    from illusion_forge.channels.feishu.ws_client import FeishuWSClient

    client = FeishuWSClient(
        app_id="cli_test", app_secret="s",
        event_handler=lambda e: None, domain="https://open.feishu.cn",
    )
    # 模拟 lark SDK 底层 WS 客户端（带 _auto_reconnect 标志）
    lark_client = mock.Mock()
    lark_client._auto_reconnect = True
    client._client = lark_client
    # _lark_loop 为 None（未 start），stop() 直接返回但已禁用自动重连
    client.stop()
    assert lark_client._auto_reconnect is False


def test_ws_requests_post_injects_timeout():
    """start() 对 lark SDK 的 requests.post 注入默认超时（源码级验证）。

    验证断网恢复修复：lark 的 _get_conn_url 用 requests.post 且未设 timeout，
    断网时同步请求可无限卡死使 WS 线程滞留。start() 必须注入默认超时，
    并在 finally 恢复原 post，避免影响其他代码。
    """
    import inspect

    from illusion_forge.channels.feishu import ws_client as ws_client_module
    from illusion_forge.channels.feishu.ws_client import FeishuWSClient

    timeout = ws_client_module._WS_HTTP_TIMEOUT
    # (connect, read) 秒，均为正数
    assert isinstance(timeout, tuple) and len(timeout) == 2
    assert timeout[0] > 0 and timeout[1] > 0

    source = inspect.getsource(FeishuWSClient.start)
    assert 'kwargs.setdefault("timeout", _WS_HTTP_TIMEOUT)' in source, (
        "start() 必须给 requests.post 注入默认超时"
    )
    assert "lark_ws_module.requests.post = original_post" in source, (
        "start() finally 必须恢复原始 requests.post"
    )
