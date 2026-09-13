"""
基于 DeepSeek API 实测响应结构：
- Chat Completions: prompt_tokens 含缓存，命中在 prompt_tokens_details.cached_tokens
- Responses/Codex: input_tokens 含缓存，命中在 input_tokens_details.cached_tokens
"""
from illusion_forge.api.codex_client import _usage_from_response
from illusion_forge.api.openai_client import _extract_openai_usage


class FakeUsage:
    """模拟 OpenAI SDK usage 对象（属性访问）。"""

    def __init__(self, **kwargs):
        self.prompt_tokens = kwargs.get("prompt_tokens")
        self.completion_tokens = kwargs.get("completion_tokens")
        self.input_tokens = kwargs.get("input_tokens")
        self.output_tokens = kwargs.get("output_tokens")
        self.prompt_tokens_details = kwargs.get("prompt_tokens_details")
        self.input_tokens_details = kwargs.get("input_tokens_details")
        self.cached_tokens = kwargs.get("cached_tokens")


def test_chat_completions_with_cache():
    """Chat Completions：prompt_tokens 含缓存，命中在 prompt_tokens_details。"""
    usage = FakeUsage(
        prompt_tokens=3091,
        completion_tokens=1,
        prompt_tokens_details=FakeUsage(cached_tokens=3072),
    )
    result = _extract_openai_usage(usage)
    assert result["input_tokens"] == 19  # 3091 - 3072
    assert result["output_tokens"] == 1
    assert result["cache_read_input_tokens"] == 3072
    assert result["cache_creation_input_tokens"] == 0


def test_chat_completions_first_call_no_cache():
    """Chat Completions 首次调用：无缓存命中，全部计入未命中。"""
    usage = FakeUsage(
        prompt_tokens=3091,
        completion_tokens=1,
        prompt_tokens_details=FakeUsage(cached_tokens=0),
    )
    result = _extract_openai_usage(usage)
    assert result["input_tokens"] == 3091
    assert result["cache_read_input_tokens"] == 0


def test_responses_api_with_cache():
    """Responses API：input_tokens 含缓存，命中在 input_tokens_details。"""
    usage = FakeUsage(
        input_tokens=3091,
        output_tokens=1,
        input_tokens_details=FakeUsage(cached_tokens=3072),
    )
    result = _extract_openai_usage(usage)
    assert result["input_tokens"] == 19
    assert result["output_tokens"] == 1
    assert result["cache_read_input_tokens"] == 3072


def test_responses_api_no_details_field():
    """Responses API 无 details 字段时回退到 0 命中。"""
    usage = FakeUsage(input_tokens=3091, output_tokens=1)
    result = _extract_openai_usage(usage)
    assert result["input_tokens"] == 3091
    assert result["cache_read_input_tokens"] == 0


def test_codex_usage_from_response_with_cache():
    """Codex：input_tokens 含缓存，命中在 input_tokens_details。"""
    response = {
        "usage": {
            "input_tokens": 3091,
            "output_tokens": 1,
            "input_tokens_details": {"cached_tokens": 3072},
        }
    }
    result = _usage_from_response(response)
    assert result.input_tokens == 19
    assert result.output_tokens == 1
    assert result.cache_read_input_tokens == 3072


def test_codex_usage_from_response_top_level_cached():
    """Codex：部分服务把 cached_tokens 放顶层（fallback）。"""
    response = {
        "usage": {
            "input_tokens": 3091,
            "output_tokens": 1,
            "cached_tokens": 3072,
        }
    }
    result = _usage_from_response(response)
    assert result.input_tokens == 19
    assert result.cache_read_input_tokens == 3072


def test_codex_usage_from_response_no_usage():
    """Codex：无 usage 时返回空快照。"""
    result = _usage_from_response({})
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.cache_read_input_tokens == 0
