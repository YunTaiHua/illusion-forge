"""headless_prompts 无头模式回调测试：问题选项格式化。"""
from __future__ import annotations

from illusion_forge.ui.headless_prompts import format_question_options


def test_format_question_options_multi_server():
    """多问题多选项格式化。"""
    questions = [
        {
            "question": "选择模型",
            "header": "Model",
            "options": [
                {"label": "sonnet", "description": "快速"},
                {"label": "opus", "description": "强力"},
            ],
            "multiSelect": False,
        }
    ]
    result = format_question_options(questions)
    assert "【Model】" in result
    assert "选择模型" in result
    assert "• sonnet — 快速" in result
    assert "• opus — 强力" in result


def test_format_question_options_empty():
    """空输入返回空字符串。"""
    assert format_question_options(None) == ""
    assert format_question_options([]) == ""
    assert format_question_options([{}]) == ""


def test_format_question_options_no_desc():
    """选项无描述时不附加 — 后缀。"""
    questions = [
        {
            "header": "Test",
            "options": [{"label": "yes"}, {"label": "no"}],
        }
    ]
    result = format_question_options(questions)
    assert "• yes" in result
    assert "• no" in result
    assert "—" not in result
