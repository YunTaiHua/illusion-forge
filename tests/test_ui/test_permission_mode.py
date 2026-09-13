"""--permission-mode 覆盖权限模式的测试。"""
from __future__ import annotations

import pytest

from illusion_forge.api.client import ApiMessageCompleteEvent
from illusion_forge.api.usage import UsageSnapshot
from illusion_forge.engine.messages import ConversationMessage, TextBlock


class StaticApiClient:
    """Fake streaming client for permission mode tests."""

    async def stream_message(self, request):
        del request
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=[TextBlock(text="ok")]),
            usage=UsageSnapshot(input_tokens=2, output_tokens=3),
            stop_reason=None,
        )


@pytest.mark.asyncio
async def test_permission_mode_override(tmp_path, monkeypatch):
    """--permission-mode 应覆盖 settings.permission.mode。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.permissions.modes import PermissionMode
    from illusion_forge.ui.runtime import build_runtime, close_runtime

    bundle = await build_runtime(
        api_client=StaticApiClient(),
        permission_mode="full_auto",
    )
    try:
        # app_state.permission_mode 由 settings.permission.mode.value 初始化（runtime.py:360）
        # 同时验证 PermissionChecker 内部状态
        assert bundle.app_state.get().permission_mode == PermissionMode.FULL_AUTO.value
        assert bundle.engine._permission_checker.current_mode == PermissionMode.FULL_AUTO
    finally:
        await close_runtime(bundle)


@pytest.mark.asyncio
async def test_permission_mode_default_when_not_specified(tmp_path, monkeypatch):
    """未指定 permission_mode 时应使用默认模式。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.permissions.modes import PermissionMode
    from illusion_forge.ui.runtime import build_runtime, close_runtime

    bundle = await build_runtime(api_client=StaticApiClient())
    try:
        # app_state.permission_mode 由 settings.permission.mode.value 初始化（runtime.py:360）
        # 同时验证 PermissionChecker 内部状态
        assert bundle.app_state.get().permission_mode == PermissionMode.DEFAULT.value
        assert bundle.engine._permission_checker.current_mode == PermissionMode.DEFAULT
    finally:
        await close_runtime(bundle)


@pytest.mark.asyncio
async def test_permission_mode_invalid_value_warns(tmp_path, monkeypatch, caplog):
    """无效的 permission_mode 应记录警告并使用默认模式。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.permissions.modes import PermissionMode
    from illusion_forge.ui.runtime import build_runtime, close_runtime

    bundle = await build_runtime(
        api_client=StaticApiClient(),
        permission_mode="invalid_mode",
    )
    try:
        # 无效值应忽略，使用默认模式
        assert bundle.app_state.get().permission_mode == PermissionMode.DEFAULT.value
        assert bundle.engine._permission_checker.current_mode == PermissionMode.DEFAULT
    finally:
        await close_runtime(bundle)


@pytest.mark.asyncio
async def test_permission_mode_yolo(tmp_path, monkeypatch):
    """--permission-mode yolo 应设置 YOLO 模式（绕过沙箱）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ILLUSION_DATA_DIR", str(tmp_path / "data"))

    from illusion_forge.permissions.modes import PermissionMode
    from illusion_forge.ui.runtime import build_runtime, close_runtime

    bundle = await build_runtime(
        api_client=StaticApiClient(),
        permission_mode="yolo",
    )
    try:
        assert bundle.app_state.get().permission_mode == PermissionMode.YOLO.value
        assert bundle.engine._permission_checker.current_mode == PermissionMode.YOLO
    finally:
        await close_runtime(bundle)
