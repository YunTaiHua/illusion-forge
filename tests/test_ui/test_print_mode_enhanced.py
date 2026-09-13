"""print 模式增强测试：终端交互回调 + 会话恢复 + 思考过程渲染。"""
from __future__ import annotations

import contextlib
import io
import json

import pytest

from illusion_forge.api.client import ApiMessageCompleteEvent, ApiTextDeltaEvent
from illusion_forge.api.usage import UsageSnapshot
from illusion_forge.engine.messages import ConversationMessage, TextBlock


class StaticApiClient:
    """Fake streaming client for print mode tests."""

    async def stream_message(self, request):
        del request
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=[TextBlock(text="ok")]),
            usage=UsageSnapshot(input_tokens=2, output_tokens=3),
            stop_reason=None,
        )


class ReasoningClient:
    """Fake client that emits reasoning + text deltas."""

    async def stream_message(self, request):
        del request
        yield ApiTextDeltaEvent(text="", reasoning="thinking...")
        yield ApiTextDeltaEvent(text="Hi!", reasoning=None)
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=[TextBlock(text="Hi!")]),
            usage=UsageSnapshot(input_tokens=2, output_tokens=3),
            stop_reason=None,
        )


@pytest.mark.asyncio
async def test_print_mode_uses_terminal_callbacks(tmp_path, monkeypatch):
    """print 模式应使用 print_mode_permission/make_print_mode_ask_user（非交互回调）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.headless import run_print_mode

    # 不应崩溃——终端回调在 EOF 时安全返回
    await run_print_mode(
        prompt="hello",
        cwd=str(tmp_path),
        api_client=StaticApiClient(),
        output_format="text",
    )


@pytest.mark.asyncio
async def test_print_mode_continue_without_session_fails(tmp_path, monkeypatch):
    """continue_session=True 但无历史会话时应报错退出。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.headless import run_print_mode

    with pytest.raises(SystemExit):
        await run_print_mode(
            prompt="continue",
            cwd=str(tmp_path),
            api_client=StaticApiClient(),
            continue_session=True,
        )


@pytest.mark.asyncio
async def test_print_mode_resume_empty_string_fails(tmp_path, monkeypatch):
    """resume='' 在 print 模式下应报错（不打开选择器）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.headless import run_print_mode

    with pytest.raises(SystemExit):
        await run_print_mode(
            prompt="resume",
            cwd=str(tmp_path),
            api_client=StaticApiClient(),
            resume="",
        )


@pytest.mark.asyncio
async def test_print_mode_reasoning_to_stderr_text_format(tmp_path, monkeypatch):
    """text 格式：思考过程输出到 stderr，前缀 [思考过程]，最终回复到 stdout。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.headless import run_print_mode

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        await run_print_mode(
            prompt="test",
            cwd=str(tmp_path),
            api_client=ReasoningClient(),
            output_format="text",
        )

    # stdout 应只有最终回复（清洁，无前缀）
    assert stdout_buf.getvalue().strip() == "Hi!"
    # stderr 应包含思考前缀和思考内容
    stderr_output = stderr_buf.getvalue()
    assert "[思考过程]" in stderr_output or "[Thinking]" in stderr_output
    assert "thinking..." in stderr_output
    # stderr 应包含最终回复标记
    assert "[最终回复]" in stderr_output or "[Assistant]" in stderr_output


@pytest.mark.asyncio
async def test_print_mode_reasoning_stream_json(tmp_path, monkeypatch):
    """stream-json 格式：reasoning 字段包含在 assistant_delta 事件中。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.headless import run_print_mode

    stdout_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf):
        await run_print_mode(
            prompt="test",
            cwd=str(tmp_path),
            api_client=ReasoningClient(),
            output_format="stream-json",
        )

    events = [json.loads(line) for line in stdout_buf.getvalue().strip().split("\n") if line]
    # 应有 reasoning delta
    reasoning_events = [e for e in events if e.get("reasoning")]
    assert len(reasoning_events) == 1
    assert reasoning_events[0]["reasoning"] == "thinking..."
    # 应有 text delta
    text_events = [e for e in events if e.get("text")]
    assert any(e["text"] == "Hi!" for e in text_events)
