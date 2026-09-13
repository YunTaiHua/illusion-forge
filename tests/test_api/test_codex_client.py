from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from illusion_forge.api.client import ApiMessageCompleteEvent, ApiMessageRequest, ApiTextDeltaEvent
from illusion_forge.api.codex_client import CodexApiClient, _convert_messages_to_codex, _resolve_codex_url
from illusion_forge.engine.messages import (
    ConversationMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

if TYPE_CHECKING:
    # typing.Self 仅用于类型注解（from __future__ import annotations 使其不在运行时求值），
    # 通过 TYPE_CHECKING 守卫以兼容 Python 3.10
    from typing import Self


class _FakeStreamResponse:
    def __init__(self, *, status_code: int = 200, lines: list[str] | None = None, body: str = "") -> None:
        self.status_code = status_code
        self._lines = lines or []
        self._body = body.encode("utf-8")

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    def __init__(self, response: _FakeStreamResponse, sink: dict[str, Any]) -> None:
        self._response = response
        self._sink = sink

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def stream(self, method: str, url: str, *, headers: dict[str, str], json: dict[str, Any]):
        self._sink["method"] = method
        self._sink["url"] = url
        self._sink["headers"] = headers
        self._sink["json"] = json
        return self._response


def _b64url(data: dict[str, object]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    import base64

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _fake_codex_token() -> str:
    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": "acct_test"}}
    return f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(payload)}.sig"


def test_convert_messages_to_codex():
    messages = [
        ConversationMessage.from_user_text("Inspect file"),
        ConversationMessage(
            role="assistant",
            content=[
                TextBlock(text="I'll inspect it."),
                ToolUseBlock(id="call_123", name="read_file", input={"path": "README.md"}),
            ],
        ),
        ConversationMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="call_123", content="hello", is_error=False)],
        ),
    ]

    converted = _convert_messages_to_codex(messages)

    assert converted[0] == {
        "role": "user",
        "content": [{"type": "input_text", "text": "Inspect file"}],
    }
    assert converted[1]["type"] == "message"
    assert converted[1]["role"] == "assistant"
    assert converted[2]["type"] == "function_call"
    assert converted[2]["call_id"] == "call_123"
    assert json.loads(converted[2]["arguments"]) == {"path": "README.md"}
    assert converted[3] == {
        "type": "function_call_output",
        "call_id": "call_123",
        "output": "hello",
    }


def test_resolve_codex_url_ignores_unrelated_base_url():
    assert _resolve_codex_url("https://api.moonshot.cn/anthropic") == "https://chatgpt.com/backend-api/codex/responses"


@pytest.mark.asyncio
async def test_codex_client_streams_text(monkeypatch):
    sink: dict[str, Any] = {}
    response = _FakeStreamResponse(
        lines=[
            'event: response.output_item.added',
            'data: {"type":"response.output_item.added","item":{"id":"msg_1","type":"message","content":[],"role":"assistant"}}',
            "",
            'event: response.output_text.delta',
            'data: {"type":"response.output_text.delta","delta":"CODE"}',
            "",
            'event: response.output_text.delta',
            'data: {"type":"response.output_text.delta","delta":"X_OK"}',
            "",
            'event: response.output_item.done',
            'data: {"type":"response.output_item.done","item":{"id":"msg_1","type":"message","content":[{"type":"output_text","text":"CODEX_OK","annotations":[]}]}}',
            "",
            'event: response.completed',
            'data: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":12,"output_tokens":3}}}',
            "",
        ]
    )
    monkeypatch.setattr(
        "illusion_forge.api.codex_client.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response, sink),
    )

    client = CodexApiClient(_fake_codex_token())
    request = ApiMessageRequest(
        model="gpt-5.4",
        messages=[ConversationMessage.from_user_text("hi")],
        system_prompt="Be helpful.",
    )
    events = [event async for event in client.stream_message(request)]

    assert [event.text for event in events if isinstance(event, ApiTextDeltaEvent)] == ["CODE", "X_OK"]
    complete = next(event for event in events if isinstance(event, ApiMessageCompleteEvent))
    assert complete.message.text == "CODEX_OK"
    assert complete.usage.input_tokens == 12
    assert complete.usage.output_tokens == 3
    assert sink["url"].endswith("/codex/responses")
    assert sink["json"]["instructions"] == "Be helpful."
    assert sink["headers"]["OpenAI-Beta"] == "responses=experimental"


@pytest.mark.asyncio
async def test_codex_client_emits_tool_use(monkeypatch):
    sink: dict[str, Any] = {}
    response = _FakeStreamResponse(
        lines=[
            'data: {"type":"response.output_item.added","item":{"id":"fc_1","type":"function_call","arguments":"","call_id":"call_abc","name":"glob"}}',
            "",
            'data: {"type":"response.output_item.done","item":{"id":"fc_1","type":"function_call","arguments":"{\\"pattern\\":\\"src/**/*.py\\"}","call_id":"call_abc","name":"glob"}}',
            "",
            'data: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":7,"output_tokens":2}}}',
            "",
        ]
    )
    monkeypatch.setattr(
        "illusion_forge.api.codex_client.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response, sink),
    )

    client = CodexApiClient(_fake_codex_token())
    request = ApiMessageRequest(
        model="gpt-5.4",
        messages=[ConversationMessage.from_user_text("glob")],
        system_prompt="Use tools.",
        tools=[{"name": "glob", "description": "find files", "input_schema": {"type": "object"}}],
    )
    events = [event async for event in client.stream_message(request)]

    complete = next(event for event in events if isinstance(event, ApiMessageCompleteEvent))
    assert complete.stop_reason == "tool_use"
    assert len(complete.message.tool_uses) == 1
    tool_use = complete.message.tool_uses[0]
    assert tool_use.id == "call_abc"
    assert tool_use.name == "glob"
    assert tool_use.input == {"pattern": "src/**/*.py"}
    assert sink["json"]["tools"][0]["name"] == "glob"


@pytest.mark.asyncio
async def test_codex_client_collects_reasoning_delta(monkeypatch):
    sink: dict[str, Any] = {}
    response = _FakeStreamResponse(
        lines=[
            'data: {"type":"response.reasoning_summary_text.delta","delta":"先分析。"}',
            "",
            'data: {"type":"response.output_text.delta","delta":"答案"}',
            "",
            'data: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":2,"output_tokens":1}}}',
            "",
        ]
    )
    monkeypatch.setattr(
        "illusion_forge.api.codex_client.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response, sink),
    )

    client = CodexApiClient(_fake_codex_token())
    request = ApiMessageRequest(
        model="gpt-5.4",
        messages=[ConversationMessage.from_user_text("hi")],
        system_prompt="Be helpful.",
    )
    events = [event async for event in client.stream_message(request)]

    reasoning_deltas = [
        event.reasoning
        for event in events
        if isinstance(event, ApiTextDeltaEvent) and event.reasoning
    ]
    assert reasoning_deltas == ["先分析。"]
    complete = next(event for event in events if isinstance(event, ApiMessageCompleteEvent))
    assert complete.message.text == "答案"
    thinking_blocks = [block for block in complete.message.content if isinstance(block, ThinkingBlock)]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0].thinking == "先分析。"


@pytest.mark.asyncio
async def test_codex_client_auth_token_resolver_refreshes_per_request(monkeypatch):
    """auth_token_resolver 在每次请求前调用，刷新的 token 出现在 Authorization 头中。"""
    sink: dict[str, Any] = {}
    calls: list[str] = []
    token_counter = {"value": "token-v1"}

    def _resolver() -> str:
        calls.append(token_counter["value"])
        return token_counter["value"]

    response = _FakeStreamResponse(
        lines=[
            'data: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":1,"output_tokens":1}}}',
            "",
        ]
    )
    monkeypatch.setattr(
        "illusion_forge.api.codex_client.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response, sink),
    )

    client = CodexApiClient(auth_token_resolver=_resolver)
    request = ApiMessageRequest(
        model="codex-mini",
        messages=[ConversationMessage.from_user_text("hi")],
    )

    # 第一次请求
    [e async for e in client.stream_message(request)]
    assert sink["headers"]["Authorization"] == "Bearer token-v1"

    # 模拟 token 刷新
    token_counter["value"] = "token-v2"

    # 第二次请求应拿到新 token
    [e async for e in client.stream_message(request)]
    assert sink["headers"]["Authorization"] == "Bearer token-v2"
    assert calls == ["token-v1", "token-v2"]


@pytest.mark.asyncio
async def test_codex_client_auth_token_resolver_raises_auth_failure(monkeypatch):
    """resolver 抛出 RuntimeError（未认证）时，应翻译为 AuthenticationFailure。"""
    from illusion_forge.api.errors import AuthenticationFailure

    def _resolver_raises() -> str:
        raise RuntimeError("未认证，请先运行 'illusion-forge auth login' 选择 Codex")

    response = _FakeStreamResponse(lines=[])
    monkeypatch.setattr(
        "illusion_forge.api.codex_client.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response, {}),
    )

    client = CodexApiClient(auth_token_resolver=_resolver_raises)
    request = ApiMessageRequest(
        model="codex-mini",
        messages=[ConversationMessage.from_user_text("hi")],
    )

    with pytest.raises(AuthenticationFailure, match="未认证"):
        [e async for e in client.stream_message(request)]
