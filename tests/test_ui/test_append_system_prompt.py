"""--append-system-prompt 追加到系统提示词的测试。"""
from __future__ import annotations


def test_append_system_prompt_adds_content():
    """--append-system-prompt 应追加到系统提示词末尾。"""
    from illusion_forge.config.settings import Settings
    from illusion_forge.prompts import build_runtime_system_prompt
    from illusion_forge.ui.runtime import _build_system_prompt_with_append

    settings = Settings()
    base = build_runtime_system_prompt(settings, cwd="/tmp")
    result = _build_system_prompt_with_append(
        settings,
        cwd="/tmp",
        latest_user_prompt=None,
        channel_hint=None,
        append_system_prompt="CUSTOM_INSTRUCTIONS",
    )
    assert "CUSTOM_INSTRUCTIONS" in result
    assert result == base + "\n\n" + "CUSTOM_INSTRUCTIONS"


def test_append_system_prompt_none_unchanged():
    """append_system_prompt=None 时系统提示词不应改变。"""
    from illusion_forge.config.settings import Settings
    from illusion_forge.prompts import build_runtime_system_prompt
    from illusion_forge.ui.runtime import _build_system_prompt_with_append

    settings = Settings()
    base = build_runtime_system_prompt(settings, cwd="/tmp")
    result = _build_system_prompt_with_append(
        settings,
        cwd="/tmp",
        latest_user_prompt=None,
        channel_hint=None,
        append_system_prompt=None,
    )
    assert result == base


def test_append_system_prompt_empty_string_unchanged():
    """append_system_prompt='' 时系统提示词不应改变。"""
    from illusion_forge.config.settings import Settings
    from illusion_forge.prompts import build_runtime_system_prompt
    from illusion_forge.ui.runtime import _build_system_prompt_with_append

    settings = Settings()
    base = build_runtime_system_prompt(settings, cwd="/tmp")
    result = _build_system_prompt_with_append(
        settings,
        cwd="/tmp",
        latest_user_prompt=None,
        channel_hint=None,
        append_system_prompt="",
    )
    assert result == base
