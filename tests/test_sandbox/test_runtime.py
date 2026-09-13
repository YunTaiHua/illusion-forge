"""沙箱运行时测试"""
from unittest.mock import MagicMock, patch

from illusion_forge.sandbox.runtime import SandboxRuntime


def test_runtime_initializes_disabled_by_default():
    runtime = SandboxRuntime()
    assert runtime.is_enabled() is False


def test_runtime_initializes_with_config():
    runtime = SandboxRuntime()
    config = {
        "enabled_platforms": [],
        "filesystem": {"allow_write": ["."], "deny_write": [], "deny_read": [], "allow_read": []},
        "network": {"allowed_domains": [], "denied_domains": []},
    }
    with (
        patch("illusion_forge.sandbox.runtime._detect_platform", return_value="linux"),
        patch("illusion_forge.sandbox.runtime._get_platform_impl") as mock_impl,
    ):
        mock_platform = MagicMock()
        mock_platform.check_dependencies.return_value = []
        mock_impl.return_value = mock_platform
        runtime.initialize(config)
        assert runtime.is_enabled() is True


def test_runtime_windows_platform_disabled():
    """Windows 原生不支持 OS 级沙箱，初始化后沙箱禁用"""
    runtime = SandboxRuntime()
    config = {
        "enabled_platforms": [],
        "filesystem": {"allow_write": ["."], "deny_write": [], "deny_read": [], "allow_read": []},
        "network": {"allowed_domains": [], "denied_domains": []},
    }
    with patch("illusion_forge.sandbox.runtime._detect_platform", return_value="windows"):
        runtime.initialize(config)
        assert runtime.is_enabled() is False


def test_runtime_unknown_platform_disabled():
    """未知平台自动降级，初始化后沙箱禁用"""
    runtime = SandboxRuntime()
    config = {
        "enabled_platforms": [],
        "filesystem": {"allow_write": ["."], "deny_write": [], "deny_read": [], "allow_read": []},
        "network": {"allowed_domains": [], "denied_domains": []},
    }
    with patch("illusion_forge.sandbox.runtime._detect_platform", return_value="unknown"):
        runtime.initialize(config)
        assert runtime.is_enabled() is False


def test_runtime_wrap_command_disabled():
    runtime = SandboxRuntime()
    result = runtime.wrap_command(["bash", "-lc", "echo"], shell="bash")
    assert result == ["bash", "-lc", "echo"]  # 未启用时返回原命令


def test_runtime_cleanup():
    runtime = SandboxRuntime()
    runtime.cleanup_after_command()  # 不应报错


def test_runtime_reset():
    runtime = SandboxRuntime()
    runtime.reset()
    assert runtime.is_enabled() is False


def test_runtime_get_platform_name():
    runtime = SandboxRuntime()
    assert runtime.get_platform_name() == ""  # 未初始化时为空
