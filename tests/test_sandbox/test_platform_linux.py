"""Linux 平台沙箱实现测试"""
from unittest.mock import patch

from illusion_forge.sandbox.platforms.base import SandboxPlatformConfig
from illusion_forge.sandbox.platforms.linux import LinuxSandboxPlatform


def test_linux_platform_is_available_with_bwrap():
    platform = LinuxSandboxPlatform()
    with patch("shutil.which", return_value="/usr/bin/bwrap"):
        assert platform.check_dependencies() == []


def test_linux_platform_missing_bwrap():
    platform = LinuxSandboxPlatform()
    with patch("shutil.which", return_value=None):
        deps = platform.check_dependencies()
        assert any("bwrap" in d for d in deps)


def test_linux_wrap_command_basic():
    platform = LinuxSandboxPlatform()
    config = SandboxPlatformConfig(
        allow_write=["."],
        deny_write=[],
        deny_read=[],
        allow_read=[],
    )
    with patch("shutil.which", return_value="/usr/bin/bwrap"):
        result = platform.wrap_command(["bash", "-lc", "echo hello"], config)
        assert "bwrap" in result[0]
        assert "--ro-bind" in result
        assert "--die-with-parent" in result


def test_linux_wrap_command_with_network_isolation():
    platform = LinuxSandboxPlatform()
    config = SandboxPlatformConfig(
        allow_write=["."],
        deny_write=[],
        deny_read=[],
        allow_read=[],
        network_enabled=True,
        proxy_env={"HTTP_PROXY": "http://127.0.0.1:8080"},
    )
    with patch("shutil.which", return_value="/usr/bin/bwrap"):
        result = platform.wrap_command(["bash", "-lc", "curl example.com"], config)
        assert "--unshare-net" in result
        assert "--setenv" in result
