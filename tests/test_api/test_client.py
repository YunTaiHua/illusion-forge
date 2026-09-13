from __future__ import annotations

from illusion_forge.api.client import AnthropicApiClient


def test_anthropic_client_uses_api_key_without_oauth_beta(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("illusion_forge.api.client.AsyncAnthropic", _FakeAsyncAnthropic)

    AnthropicApiClient(api_key="api-key")

    assert captured["api_key"] == "api-key"
    assert "default_headers" not in captured
