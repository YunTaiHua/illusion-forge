"""macOS Seatbelt 沙箱测试"""
from unittest.mock import patch

from illusion_forge.sandbox.platforms.base import SandboxPlatformConfig
from illusion_forge.sandbox.platforms.macos import MacOSSandboxPlatform


def test_macos_platform_available():
    platform = MacOSSandboxPlatform()
    with patch("shutil.which", return_value="/usr/bin/sandbox-exec"):
        assert platform.check_dependencies() == []


def test_macos_generates_seatbelt_profile():
    platform = MacOSSandboxPlatform()
    config = SandboxPlatformConfig(
        allow_write=["/tmp/test"],
        deny_write=["/etc/passwd"],
        deny_read=["/private/keys"],
        allow_read=[],
    )
    profile = platform._generate_seatbelt_profile(config, "test_tag")
    assert "(version 1)" in profile
    assert "(deny default" in profile
    assert "/tmp/test" in profile
    assert "/etc/passwd" in profile


def test_macos_wrap_command_format():
    platform = MacOSSandboxPlatform()
    config = SandboxPlatformConfig(
        allow_write=["."],
        deny_write=[],
        deny_read=[],
        allow_read=[],
    )
    result = platform.wrap_command(["bash", "-lc", "echo hello"], config)
    assert "sandbox-exec" in " ".join(result)
    assert "-p" in " ".join(result)
