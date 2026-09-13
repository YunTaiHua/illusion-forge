"""terminal 端缺失 env/model 时的友好提示测试。"""
from __future__ import annotations

import pytest


def test_build_runtime_exits_gracefully_on_missing_api_key(tmp_path, monkeypatch):
    """无 API key 时 build_runtime 应优雅退出而非抛出异常堆栈。"""
    import sys

    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    # 确保无 credentials 和无 env 配置
    from illusion_forge.config.settings import load_settings
    load_settings()
    # 模拟无 api_key 的 anthropic env
    from illusion_forge.config.settings import Settings
    extras = {"env_1": {"api_format": "anthropic", "base_url": "", "api_key": "", "model_1": "claude-sonnet-4-6"}}
    new_settings = Settings.model_validate({"model": "env_1.model_1", **extras})
    from illusion_forge.config import save_settings
    save_settings(new_settings)

    # 确保 illusion_forge.ui.web.ws_host 不在 sys.modules 中（终端模式），
    # 否则 build_runtime 会走 web 降级路径而不抛出 SystemExit
    monkeypatch.delitem(sys.modules, "illusion_forge.ui.web.ws_host", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        from illusion_forge.ui.runtime import build_runtime
        try:
            import asyncio
            asyncio.run(build_runtime())
        except ValueError:
            pytest.fail("ValueError should be caught, not propagated")
    assert exc_info.value.code == 1


def test_rebuild_api_client_sets_auth_status_missing_on_failure(tmp_path, monkeypatch):
    """_rebuild_api_client 在 API key 缺失时应设置 auth_status=missing 而非崩溃。"""
    monkeypatch.setenv("ILLUSION_CONFIG_DIR", str(tmp_path / "config"))
    from illusion_forge.config.settings import Settings
    extras = {"env_1": {"api_format": "anthropic", "base_url": "", "api_key": "", "model_1": "claude-sonnet-4-6"}}
    settings = Settings.model_validate({"model": "env_1.model_1", **extras})

    # 创建一个 mock bundle
    from unittest.mock import MagicMock
    bundle = MagicMock()
    bundle.cwd = str(tmp_path)
    bundle.app_state.get.return_value.auth_status = "configured"

    from illusion_forge.ui.runtime import _rebuild_api_client
    # 不应抛出异常
    _rebuild_api_client(bundle, settings)

    # 验证 auth_status 被设为 missing
    assert bundle.app_state.get.return_value.auth_status == "missing"
