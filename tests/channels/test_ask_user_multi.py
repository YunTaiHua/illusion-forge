"""渠道 ask_user_question 多问题处理测试。"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest


class FakeChannel:
    """假渠道，记录发送的消息并按预设回复。"""

    def __init__(self, replies: list[str]):
        self.sent_texts: list[str] = []
        self._replies = list(replies)
        self._reply_idx = 0

    async def send_text(self, chat_id: str, text: str, **kwargs: Any) -> None:
        self.sent_texts.append(text)


class FakeChannelRunner:
    """最小化 ChannelRunner，仅暴露 _make_ask_user_prompt / _wait_reply。"""

    def __init__(self, channel: FakeChannel, replies: list[str]):
        self.channel = channel
        self._replies = list(replies)
        self._reply_idx = 0

    async def _wait_reply(self, chat_id: str, timeout: float) -> str:
        if self._reply_idx >= len(self._replies):
            raise asyncio.TimeoutError
        reply = self._replies[self._reply_idx]
        self._reply_idx += 1
        return reply

    def _is_zh(self) -> bool:
        return True

    # 绑定真实方法
    _make_ask_user_prompt = None  # 由测试中注入


@pytest.mark.asyncio
async def test_channel_single_question_returns_str():
    """单问题应返回字符串（原有行为）。"""
    from illusion_forge.channels import ChannelRunner

    fake = FakeChannel([])
    runner = FakeChannelRunner(fake, replies=["选项A"])
    # 从真实 ChannelRunner 绑定方法
    runner._make_ask_user_prompt = ChannelRunner._make_ask_user_prompt.__get__(runner, FakeChannelRunner)

    callback = runner._make_ask_user_prompt("chat1")
    questions = [
        {"question": "选哪个?", "header": "Choice", "options": [
            {"label": "选项A", "description": "a"},
            {"label": "选项B", "description": "b"},
        ], "multiSelect": False},
    ]
    result = await callback("选哪个?", questions)

    assert result == "选项A"
    assert len(fake.sent_texts) == 1
    assert "选哪个?" in fake.sent_texts[0]
    assert "选项A" in fake.sent_texts[0]


@pytest.mark.asyncio
async def test_channel_multi_question_returns_dict():
    """多问题应逐个询问并返回 dict。"""
    from illusion_forge.channels import ChannelRunner

    fake = FakeChannel([])
    runner = FakeChannelRunner(fake, replies=["答案1", "答案2", "答案3"])
    runner._make_ask_user_prompt = ChannelRunner._make_ask_user_prompt.__get__(runner, FakeChannelRunner)

    callback = runner._make_ask_user_prompt("chat1")
    questions = [
        {"question": "问题1?", "header": "H1", "options": [{"label": "A", "description": "a"}], "multiSelect": False},
        {"question": "问题2?", "header": "H2", "options": [{"label": "B", "description": "b"}], "multiSelect": False},
        {"question": "问题3?", "header": "H3", "options": [{"label": "C", "description": "c"}], "multiSelect": False},
    ]
    result = await callback("多问题", questions)

    assert isinstance(result, dict)
    assert result["H1"] == "答案1"
    assert result["H2"] == "答案2"
    assert result["H3"] == "答案3"
    # 应发送 3 条消息
    assert len(fake.sent_texts) == 3
    # 每条消息含序号
    assert "[1/3]" in fake.sent_texts[0]
    assert "[2/3]" in fake.sent_texts[1]
    assert "[3/3]" in fake.sent_texts[2]


@pytest.mark.asyncio
async def test_channel_multiselect_returns_list():
    """multiSelect=True 应返回 list（逗号分隔拆分）。"""
    from illusion_forge.channels import ChannelRunner

    fake = FakeChannel([])
    runner = FakeChannelRunner(fake, replies=["选项A,选项B"])
    runner._make_ask_user_prompt = ChannelRunner._make_ask_user_prompt.__get__(runner, FakeChannelRunner)

    callback = runner._make_ask_user_prompt("chat1")
    questions = [
        {"question": "选哪些?", "header": "Multi", "options": [
            {"label": "选项A", "description": "a"},
            {"label": "选项B", "description": "b"},
        ], "multiSelect": True},
    ]
    result = await callback("选哪些?", questions)

    assert isinstance(result, dict)
    assert result["Multi"] == ["选项A", "选项B"]
    # 消息应含多选提示
    assert "可多选" in fake.sent_texts[0]


@pytest.mark.asyncio
async def test_channel_no_questions_returns_str():
    """questions=None 应直接返回回复字符串（原有行为）。"""
    from illusion_forge.channels import ChannelRunner

    fake = FakeChannel([])
    runner = FakeChannelRunner(fake, replies=["回复"])
    runner._make_ask_user_prompt = ChannelRunner._make_ask_user_prompt.__get__(runner, FakeChannelRunner)

    callback = runner._make_ask_user_prompt("chat1")
    result = await callback("问题?", None)

    assert result == "回复"
    assert len(fake.sent_texts) == 1
