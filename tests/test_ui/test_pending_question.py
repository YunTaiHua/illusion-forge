"""Pending question 持久化与 print 模式非交互问答测试。"""
from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_save_load_delete_pending_question(tmp_path, monkeypatch):
    """pending question 的保存、加载、删除生命周期。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.services.session_storage import (
        delete_pending_question,
        load_pending_question,
        save_pending_question,
    )

    cwd = str(tmp_path)
    session_id = "test123"
    questions = [
        {"question": "哪个模型?", "header": "Model", "options": [{"label": "A", "description": "a"}]},
    ]

    # 保存
    path = save_pending_question(
        cwd=cwd,
        session_id=session_id,
        tool_use_id="tu_001",
        questions=questions,
        question_text="哪个模型?",
    )
    assert path.exists()

    # 加载
    data = load_pending_question(cwd, session_id)
    assert data is not None
    assert data["session_id"] == session_id
    assert data["tool_use_id"] == "tu_001"
    assert data["questions"] == questions
    assert data["question_text"] == "哪个模型?"

    # 删除
    assert delete_pending_question(cwd, session_id) is True
    assert not path.exists()
    assert load_pending_question(cwd, session_id) is None


@pytest.mark.asyncio
async def test_load_pending_question_none_when_missing(tmp_path, monkeypatch):
    """不存在的 pending question 返回 None。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.services.session_storage import load_pending_question

    assert load_pending_question(str(tmp_path), "nonexistent") is None


@pytest.mark.asyncio
async def test_make_print_mode_ask_user_persists_and_returns_marker(tmp_path, monkeypatch):
    """print 模式回调应持久化问题并返回 PENDING_ANSWER_MARKER。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.services.session_storage import load_pending_question
    from illusion_forge.ui.headless_prompts import PENDING_ANSWER_MARKER, make_print_mode_ask_user

    state: dict = {}
    callback = make_print_mode_ask_user(
        cwd=str(tmp_path),
        session_id="sess123",
        state=state,
    )

    questions = [
        {"question": "选哪个?", "header": "Choice", "options": [{"label": "A", "description": "a"}]},
    ]
    result = await callback("选哪个?", questions)

    # 返回特殊标记
    assert result == PENDING_ANSWER_MARKER
    # 设置了状态标志
    assert state.get("pending_question_raised") is True
    # 持久化了问题
    data = load_pending_question(str(tmp_path), "sess123")
    assert data is not None
    assert data["questions"] == questions
    assert data["question_text"] == "选哪个?"


@pytest.mark.asyncio
async def test_make_print_mode_ask_user_no_session_id_skips_persist(tmp_path, monkeypatch):
    """session_id=None 时回调仍返回标记但不持久化。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.ui.headless_prompts import PENDING_ANSWER_MARKER, make_print_mode_ask_user

    state: dict = {}
    callback = make_print_mode_ask_user(cwd=str(tmp_path), session_id=None, state=state)

    result = await callback("问题?", None)
    assert result == PENDING_ANSWER_MARKER
    assert state.get("pending_question_raised") is True


def test_inject_answer_replaces_pending_marker():
    """_inject_answer_to_pending_tool_result 应替换 PENDING_ANSWER_MARKER。"""
    from illusion_forge.ui.headless import _inject_answer_to_pending_tool_result
    from illusion_forge.ui.headless_prompts import PENDING_ANSWER_MARKER

    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "tu_1", "name": "ask_user_question"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": PENDING_ANSWER_MARKER, "is_error": False}]},
    ]

    result = _inject_answer_to_pending_tool_result(messages, "用户的答案")

    # 最后一条 user message 的 tool_result 应被替换
    tool_result = result[2]["content"][0]
    assert tool_result["content"] == "用户的答案"
    assert tool_result["is_error"] is False


def test_inject_answer_no_marker_returns_unchanged():
    """没有 PENDING_ANSWER_MARKER 时消息不变。"""
    from illusion_forge.ui.headless import _inject_answer_to_pending_tool_result

    messages = [
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "正常回答"}]},
    ]

    result = _inject_answer_to_pending_tool_result(messages, "新答案")
    # 内容不变
    assert result[0]["content"][0]["content"] == "正常回答"


def test_inject_answer_finds_last_marker():
    """多个 markers 时应替换最后一个。"""
    from illusion_forge.ui.headless import _inject_answer_to_pending_tool_result
    from illusion_forge.ui.headless_prompts import PENDING_ANSWER_MARKER

    messages = [
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": PENDING_ANSWER_MARKER}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_2", "content": PENDING_ANSWER_MARKER}]},
    ]

    result = _inject_answer_to_pending_tool_result(messages, "答案")
    # 第一个不变
    assert result[0]["content"][0]["content"] == PENDING_ANSWER_MARKER
    # 最后一个被替换
    assert result[1]["content"][0]["content"] == "答案"


def test_format_multi_answer_single_question_returns_as_is():
    """单问题时原样返回（不需要 JSON）。"""
    from illusion_forge.ui.headless import _format_multi_answer

    questions = [{"header": "Model", "question": "哪个?"}]
    result = _format_multi_answer("sonnet", questions)
    assert result == "sonnet"


def test_format_multi_answer_json_parsed_to_header_value_lines():
    """多问题 JSON 答案解析为 header: value 行。"""
    from illusion_forge.ui.headless import _format_multi_answer

    questions = [
        {"header": "水果", "question": "?"},
        {"header": "OS", "question": "?"},
        {"header": "Emoji", "question": "?"},
    ]
    prompt = '{"水果": "草莓", "OS": "Windows", "Emoji": "少用点"}'
    result = _format_multi_answer(prompt, questions)
    assert "水果: 草莓" in result
    assert "OS: Windows" in result
    assert "Emoji: 少用点" in result


def test_format_multi_answer_multiselect_list_expanded():
    """multiSelect 的 list 值展开为多行 header: item。"""
    from illusion_forge.ui.headless import _format_multi_answer

    questions = [
        {"header": "水果", "question": "?", "multiSelect": True},
        {"header": "OS", "question": "?"},
    ]
    prompt = '{"水果": ["草莓", "芒果"], "OS": "Linux"}'
    result = _format_multi_answer(prompt, questions)
    assert "水果: 草莓" in result
    assert "水果: 芒果" in result
    assert "OS: Linux" in result


def test_format_multi_answer_non_json_returns_as_is():
    """非 JSON 输入原样返回（向后兼容）。"""
    from illusion_forge.ui.headless import _format_multi_answer

    questions = [{"header": "A", "question": "?"}, {"header": "B", "question": "?"}]
    result = _format_multi_answer("随便写的答案", questions)
    assert result == "随便写的答案"


def test_format_multi_answer_invalid_json_returns_as_is():
    """JSON 解析失败时原样返回。"""
    from illusion_forge.ui.headless import _format_multi_answer

    questions = [{"header": "A", "question": "?"}, {"header": "B", "question": "?"}]
    result = _format_multi_answer("{invalid json", questions)
    assert result == "{invalid json"


def test_format_multi_answer_empty_questions_returns_as_is():
    """questions 为空时原样返回。"""
    from illusion_forge.ui.headless import _format_multi_answer

    assert _format_multi_answer("答案", None) == "答案"
    assert _format_multi_answer("答案", []) == "答案"


@pytest.mark.asyncio
async def test_make_print_mode_plan_approval_persists_and_returns_marker(tmp_path, monkeypatch):
    """make_print_mode_plan_approval 应持久化计划并返回 pending 标记。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.services.session_storage import load_pending_plan_approval
    from illusion_forge.ui.headless_prompts import PENDING_PLAN_APPROVAL_MARKER, make_print_mode_plan_approval

    state: dict = {}
    callback = make_print_mode_plan_approval(
        cwd=str(tmp_path),
        session_id="test-session",
        state=state,
    )

    approved, feedback = await callback("# My Plan\nStep 1")

    # 返回 (False, PENDING_PLAN_APPROVAL_MARKER)
    assert approved is False
    assert feedback == PENDING_PLAN_APPROVAL_MARKER
    # 设置了状态标志
    assert state.get("pending_plan_approval_raised") is True
    # 持久化了计划内容
    loaded = load_pending_plan_approval(str(tmp_path), "test-session")
    assert loaded is not None
    assert loaded["plan"] == "# My Plan\nStep 1"
    assert loaded["session_id"] == "test-session"


@pytest.mark.asyncio
async def test_make_print_mode_plan_approval_no_session_id_skips_persist(tmp_path, monkeypatch):
    """session_id=None 时回调仍返回标记但不持久化。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.services.session_storage import load_pending_plan_approval
    from illusion_forge.ui.headless_prompts import PENDING_PLAN_APPROVAL_MARKER, make_print_mode_plan_approval

    state: dict = {}
    callback = make_print_mode_plan_approval(
        cwd=str(tmp_path),
        session_id=None,
        state=state,
    )

    approved, feedback = await callback("# My Plan\nStep 1")

    assert approved is False
    assert feedback == PENDING_PLAN_APPROVAL_MARKER
    assert state.get("pending_plan_approval_raised") is True
    # 未持久化
    assert load_pending_plan_approval(str(tmp_path), "test-session") is None


@pytest.mark.asyncio
async def test_make_print_mode_permission_persists_and_returns_false(tmp_path, monkeypatch):
    """测试 make_print_mode_permission：未授权工具应持久化并返回 False"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    from illusion_forge.services.session_storage import load_pending_permission
    from illusion_forge.ui.headless_prompts import make_print_mode_permission

    cwd = str(tmp_path / "project")
    session_id = "test-perm-001"
    state: dict = {}

    callback = make_print_mode_permission(cwd=cwd, session_id=session_id, state=state)

    # 未获允许的工具（print 模式无永久允许，直接请求确认）
    result = await callback("write_file", "Mutating tools require confirmation")
    assert result is False
    assert state.get("pending_permission_raised") is True

    # 验证已持久化
    pending = load_pending_permission(cwd, session_id)
    assert pending is not None
    assert pending["tool_name"] == "write_file"
    assert pending["approved"] is False


@pytest.mark.asyncio
async def test_make_print_mode_permission_auto_approve_for_cron(tmp_path, monkeypatch):
    """cron 投递任务（ILLUSION_CRON_AUTO_APPROVE=1）：权限自动批准（含高危）。

    对齐渠道端 `_make_permission_prompt` 行为；不持久化、不设置 pending flag。
    """
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ILLUSION_CRON_AUTO_APPROVE", "1")
    from illusion_forge.services.session_storage import load_pending_permission
    from illusion_forge.ui.headless_prompts import make_print_mode_permission

    cwd = str(tmp_path / "project")
    session_id = "test-perm-auto"
    state: dict = {}

    callback = make_print_mode_permission(cwd=cwd, session_id=session_id, state=state)

    # 高危命令权限也应自动批准
    result = await callback("bash", "rm -rf /", high_risk=True)
    assert result is True
    assert state.get("pending_permission_raised") is None
    assert load_pending_permission(cwd, session_id) is None

    # 普通工具权限同样自动批准
    result = await callback("write_file", "Mutating tools require confirmation")
    assert result is True


@pytest.mark.asyncio
async def test_make_print_mode_permission_approved_pending_returns_true(tmp_path, monkeypatch):
    """测试 make_print_mode_permission：pending 文件 approved=true 时应放行并删除"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    from illusion_forge.services.session_storage import load_pending_permission, save_pending_permission
    from illusion_forge.ui.headless_prompts import make_print_mode_permission

    cwd = str(tmp_path / "project")
    session_id = "test-perm-002"
    state: dict = {}

    # 预置一个 approved=true 的 pending 文件（模拟 Turn 2 resume 场景）
    save_pending_permission(cwd=cwd, session_id=session_id, tool_name="write_file", reason="test")
    # 手动更新 approved 为 true（模拟 app.py 解析 Y 后的更新）
    from illusion_forge.services.session_storage import _pending_permission_path
    path = _pending_permission_path(cwd, session_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["approved"] = True
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    callback = make_print_mode_permission(cwd=cwd, session_id=session_id, state=state)
    result = await callback("write_file", "Mutating tools require confirmation")
    assert result is True
    # 一次性，用完即删
    assert load_pending_permission(cwd, session_id) is None


@pytest.mark.asyncio
async def test_make_print_mode_permission_no_session_id_skips_persist(tmp_path, monkeypatch):
    """测试 make_print_mode_permission：无 session_id 时不持久化（与 ask_user 一致）"""
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))
    from illusion_forge.ui.headless_prompts import make_print_mode_permission

    cwd = str(tmp_path / "project")
    state: dict = {}

    callback = make_print_mode_permission(cwd=cwd, session_id=None, state=state)
    result = await callback("write_file", "test")
    assert result is False
    assert state.get("pending_permission_raised") is True
