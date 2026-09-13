"""代理环境变量生成测试"""
from illusion_forge.sandbox.proxy.env_vars import generate_sandbox_proxy_env


def test_generate_sandbox_proxy_env_basic():
    env = generate_sandbox_proxy_env(http_port=8080, socks_port=1080, platform_name="linux")
    assert env["HTTP_PROXY"] == "http://127.0.0.1:8080"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:8080"
    assert env["ALL_PROXY"] == "socks5h://127.0.0.1:1080"
    assert env["SANDBOX_RUNTIME"] == "1"
    assert "NO_PROXY" in env
    assert "localhost" in env["NO_PROXY"]


def test_generate_sandbox_proxy_env_linux_git_ssh():
    env = generate_sandbox_proxy_env(http_port=8080, socks_port=1080, platform_name="linux")
    assert "GIT_SSH_COMMAND" in env
    assert "socat" in env["GIT_SSH_COMMAND"]


def test_generate_sandbox_proxy_env_macos_git_ssh():
    env = generate_sandbox_proxy_env(http_port=8080, socks_port=1080, platform_name="macos")
    assert "GIT_SSH_COMMAND" in env
    assert "nc" in env["GIT_SSH_COMMAND"]


def test_generate_sandbox_proxy_env_sets_tmpdir():
    env = generate_sandbox_proxy_env(http_port=8080, socks_port=1080, platform_name="linux")
    assert "TMPDIR" in env
