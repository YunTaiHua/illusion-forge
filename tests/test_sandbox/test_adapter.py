"""沙箱适配器测试 — 测试新的 SandboxManager API"""
from unittest.mock import patch

from illusion_forge.config.settings import (
    SandboxFilesystemSettings,
    SandboxNetworkSettings,
    SandboxSettings,
    Settings,
)
from illusion_forge.sandbox.adapter import SandboxManager


def test_manager_singleton():
    """SandboxManager 是单例"""
    m1 = SandboxManager()
    m2 = SandboxManager()
    assert m1 is m2


def test_availability_runtime_unavailable():
    """沙箱恒开启：运行时未就绪时 available=False（active=False）"""
    manager = SandboxManager()
    manager.reset()
    settings = Settings(sandbox=SandboxSettings())
    with patch.object(manager, "_runtime") as mock_runtime:
        mock_runtime.is_enabled.return_value = False
        avail = manager.get_availability(settings)
        assert avail.available is False
        assert avail.active is False


def test_availability_enabled():
    """沙箱恒开启：运行时就绪时返回 active"""
    manager = SandboxManager()
    manager.reset()
    settings = Settings(sandbox=SandboxSettings())
    # Mock 运行时为已启用状态
    with patch.object(manager, "_runtime") as mock_runtime:
        mock_runtime.is_enabled.return_value = True
        avail = manager.get_availability(settings)
        assert avail.available is True
        assert avail.active is True


def test_should_use_sandbox_runtime_unavailable():
    """沙箱恒开启：运行时未就绪时不使用沙箱"""
    manager = SandboxManager()
    manager.reset()
    settings = Settings(sandbox=SandboxSettings())
    with patch.object(manager, "_runtime") as mock_runtime:
        mock_runtime.is_enabled.return_value = False
        assert manager.should_use_sandbox("echo hello", settings=settings) is False


def test_should_use_sandbox_enabled():
    """沙箱恒开启：运行时就绪时应使用沙箱"""
    manager = SandboxManager()
    manager.reset()
    settings = Settings(sandbox=SandboxSettings())
    with patch.object(manager, "_runtime") as mock_runtime:
        mock_runtime.is_enabled.return_value = True
        assert manager.should_use_sandbox("echo hello", settings=settings) is True


def test_excluded_command_matching():
    """排除命令匹配"""
    manager = SandboxManager()
    manager.reset()
    settings = Settings(sandbox=SandboxSettings(
        excluded_commands=["npm test", "make:*"],
    ))
    with patch.object(manager, "_runtime") as mock_runtime:
        mock_runtime.is_enabled.return_value = True
        assert manager.should_use_sandbox("npm test", settings=settings) is False
        assert manager.should_use_sandbox("make:build", settings=settings) is False
        assert manager.should_use_sandbox("rm -rf /", settings=settings) is True


def test_excluded_command_with_env_prefix():
    """排除命令匹配（带环境变量前缀）"""
    manager = SandboxManager()
    manager.reset()
    settings = Settings(sandbox=SandboxSettings(
        excluded_commands=["npm test"],
    ))
    with patch.object(manager, "_runtime") as mock_runtime:
        mock_runtime.is_enabled.return_value = True
        assert manager.should_use_sandbox("NODE_ENV=production npm test", settings=settings) is False


def test_excluded_command_compound():
    """复合命令中排除命令匹配"""
    manager = SandboxManager()
    manager.reset()
    settings = Settings(sandbox=SandboxSettings(
        excluded_commands=["echo safe"],
    ))
    with patch.object(manager, "_runtime") as mock_runtime:
        mock_runtime.is_enabled.return_value = True
        # 复合命令中包含排除命令的子命令
        assert manager.should_use_sandbox("echo safe && rm -rf /", settings=settings) is False


def test_settings_to_config():
    """配置转换正确性"""
    manager = SandboxManager()
    settings = Settings(sandbox=SandboxSettings(
        network=SandboxNetworkSettings(allowed_domains=["*.github.com"]),
        filesystem=SandboxFilesystemSettings(deny_write=[".git/hooks"]),
    ))
    config = manager._settings_to_config(settings.sandbox)
    assert config["network"]["allowed_domains"] == ["*.github.com"]
    assert config["filesystem"]["deny_write"] == [".git/hooks"]
