"""渠道会话提前落盘测试

验证 _run_agent 进入 agent turn 前会先把会话索引落盘，
避免进程崩溃后下次启动新建会话而非接续。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_run_agent_persists_session_before_build_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_run_agent 应在 build_runtime 之前先 save 会话索引

    构造一个会在 build_runtime 抛异常的场景，验证会话文件已落盘
    （即使本轮 agent turn 未完成，下次启动也能接续）。
    """
    from illusion_forge.channels import ChannelRunner
    from illusion_forge.channels.base import InboundMessage

    # 构造 mock channel：channel 不是任何已知渠道类型，
    # _create_session_store 会落到默认 FeishuSessionStore 分支。
    channel = MagicMock()
    channel.send_text = AsyncMock()
    channel.start_typing = AsyncMock()
    channel.stop_typing = AsyncMock()
    channel.config = MagicMock()
    channel.config.markdown_support = None
    channel.name = "test"

    settings = MagicMock()
    settings.resolve_api_key.return_value = "sk-test"
    settings._active_env_key = ""

    runner = ChannelRunner(
        channel=channel, settings=settings, session_data_dir=tmp_path,
    )
    # _keep_typing_alive 是个无限循环 task，patch 成空操作
    monkeypatch.setattr(
        runner, "_keep_typing_alive", AsyncMock(return_value=None)
    )

    msg = InboundMessage(
        chat_id="u1", user_id="u1", user_name="tester",
        text="hi", chat_type="dm",
        message_id="m1", is_bot=False,
    )

    # build_runtime 抛异常，模拟 agent turn 未完成
    with patch(
        "illusion_forge.ui.runtime.build_runtime", side_effect=RuntimeError("boom")
    ), patch(
        "illusion_forge.channels.config.load_channels_config", return_value=MagicMock()
    ), patch(
        "illusion_forge.prompts.channel_hints.get_channel_hint", return_value=""
    ), patch(
        "illusion_forge.prompts.channel_hints.list_active_sessions", return_value=[]
    ):
        # _run_agent 内部捕获 build_runtime 异常并发错误消息，不抛出
        await runner._run_agent(msg)

    # 验证会话文件已落盘（即使 agent turn 失败）
    session_files = list(tmp_path.glob("*.json"))
    assert len(session_files) == 1, "会话索引应在 build_runtime 前落盘"
    data = json.loads(session_files[0].read_text(encoding="utf-8"))
    assert data.get("session_id"), "落盘的 session_id 非空"
