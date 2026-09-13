"""渠道抽象基类测试。"""
from __future__ import annotations

import pytest

from illusion_forge.channels.base import Channel, InboundMessage


def test_inbound_message_dataclass():
    """InboundMessage 能正确构造，带默认值。"""
    msg = InboundMessage(
        text="hello",
        chat_id="oc_test",
        chat_type="group",
        user_id="ou_user",
        user_name="alice",
        message_id="om_msg",
    )
    assert msg.text == "hello"
    assert msg.chat_type == "group"
    assert msg.is_bot is False  # 默认
    assert msg.thread_id == ""  # 默认


def test_channel_is_abstract():
    """Channel 是抽象基类，不能直接实例化。"""
    with pytest.raises(TypeError):
        Channel()  # type: ignore[abstract]


def test_channel_subclass_must_implement_abstracts():
    """子类必须实现所有抽象方法才能实例化。"""

    class PartialChannel(Channel):
        name = "partial"

    with pytest.raises(TypeError):
        PartialChannel()  # type: ignore[abstract]
