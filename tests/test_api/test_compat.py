from __future__ import annotations

from illusion_forge.api.compat import merge_reasoning_text, parse_tool_arguments, split_thinking_from_text


def test_parse_tool_arguments_supports_fenced_json():
    raw = """```json
{"path":"src/main.py","offset":0}
```"""
    parsed = parse_tool_arguments(raw)
    assert parsed == {"path": "src/main.py", "offset": 0}


def test_parse_tool_arguments_supports_python_literal_dict():
    parsed = parse_tool_arguments("{'path': 'src/main.py', 'limit': 20}")
    assert parsed == {"path": "src/main.py", "limit": 20}


def test_split_thinking_from_text_extracts_think_blocks():
    text, thinking = split_thinking_from_text("<think>分析一</think>Answer")
    assert text == "Answer"
    assert thinking == "分析一"


def test_merge_reasoning_text_deduplicates_overlaps():
    merged = merge_reasoning_text("先检查文件", "先检查文件并提取函数")
    assert merged == "先检查文件并提取函数"

