"""沙箱配置 schema 验证测试"""
import pytest
from pydantic import ValidationError

from illusion_forge.config.settings import (
    SandboxNetworkSettings,
    SandboxSettings,
)


def test_sandbox_settings_has_new_fields():
    """验证 SandboxSettings 包含所有新字段"""
    s = SandboxSettings()
    assert hasattr(s, 'excluded_commands')
    assert s.excluded_commands == []
    assert hasattr(s, 'ignore_violations')
    assert s.ignore_violations == {}
    assert hasattr(s, 'enable_weaker_nested_sandbox')
    assert s.enable_weaker_nested_sandbox is False
    assert hasattr(s, 'mandatory_deny_search_depth')
    assert s.mandatory_deny_search_depth == 3
    assert hasattr(s, 'allow_git_config')
    assert s.allow_git_config is False


def test_network_settings_has_new_fields():
    """验证 SandboxNetworkSettings 包含所有新字段"""
    n = SandboxNetworkSettings()
    assert hasattr(n, 'allow_unix_sockets')
    assert n.allow_unix_sockets == []
    assert hasattr(n, 'allow_all_unix_sockets')
    assert n.allow_all_unix_sockets is False
    assert hasattr(n, 'allow_local_binding')
    assert n.allow_local_binding is False
    assert hasattr(n, 'http_proxy_port')
    assert n.http_proxy_port is None
    assert hasattr(n, 'socks_proxy_port')
    assert n.socks_proxy_port is None


def test_domain_validation_rejects_wildcard():
    """拒绝过于宽泛的域名通配符"""
    with pytest.raises(ValidationError):
        SandboxNetworkSettings(allowed_domains=["*"])


def test_domain_validation_rejects_broad_tld():
    """拒绝 *.com 等宽泛 TLD"""
    with pytest.raises(ValidationError):
        SandboxNetworkSettings(allowed_domains=["*.com"])


def test_domain_validation_accepts_subdomain_wildcard():
    """接受 *.example.com 格式"""
    n = SandboxNetworkSettings(allowed_domains=["*.example.com"])
    assert n.allowed_domains == ["*.example.com"]


def test_domain_validation_rejects_url_format():
    """拒绝包含 :// 的格式"""
    with pytest.raises(ValidationError):
        SandboxNetworkSettings(allowed_domains=["https://example.com"])


def test_domain_validation_accepts_localhost():
    """localhost 始终允许"""
    n = SandboxNetworkSettings(allowed_domains=["localhost"])
    assert n.allowed_domains == ["localhost"]


def test_mandatory_deny_search_depth_range():
    """mandatory_deny_search_depth 范围 1-10"""
    s = SandboxSettings(mandatory_deny_search_depth=5)
    assert s.mandatory_deny_search_depth == 5


def test_mandatory_deny_search_depth_out_of_range():
    """mandatory_deny_search_depth 超出范围应报错"""
    with pytest.raises(ValidationError):
        SandboxSettings(mandatory_deny_search_depth=0)
    with pytest.raises(ValidationError):
        SandboxSettings(mandatory_deny_search_depth=11)


def test_domain_validation_accepts_normal_domain():
    """接受正常域名"""
    n = SandboxNetworkSettings(allowed_domains=["api.github.com"])
    assert n.allowed_domains == ["api.github.com"]
