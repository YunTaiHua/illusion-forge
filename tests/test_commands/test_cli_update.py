"""CLI update 子命令测试：基于 GitHub Releases 的版本检查与下载指引。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from illusion_forge.cli import app
from illusion_forge.commands.misc import RELEASES_PAGE_URL, _check_latest_release
from illusion_forge.config.i18n import t


def test_update_network_error_exits_nonzero():
    """无法获取最新版本时输出网络错误并以非零码退出。"""
    with patch("illusion_forge.commands.misc._check_latest_release", return_value=None):
        result = CliRunner().invoke(app, ["update"])
    assert result.exit_code == 1
    assert t("update_network_error") in result.output


def test_update_already_latest():
    """最新版本等于当前版本时提示已是最新。"""
    with patch("illusion_forge.commands.misc._check_latest_release", return_value="0.4.13"), \
         patch("illusion_forge.commands.misc._get_current_version", return_value="0.4.13"):
        result = CliRunner().invoke(app, ["update"])
    assert result.exit_code == 0
    assert t("update_latest", version="0.4.13") in result.output


def test_update_available_prints_download_hint():
    """有新版本时输出版本对比与 GitHub Releases 下载指引，不执行任何安装。"""
    with patch("illusion_forge.commands.misc._check_latest_release", return_value="0.5.0"), \
         patch("illusion_forge.commands.misc._get_current_version", return_value="0.4.13"):
        result = CliRunner().invoke(app, ["update"])
    assert result.exit_code == 0
    assert t("update_available", current="0.4.13", latest="0.5.0") in result.output
    assert RELEASES_PAGE_URL in result.output


def test_check_latest_release_strips_tag_prefix():
    """latest release 的 tag_name 去掉前导 v 后作为版本号返回。"""
    resp = MagicMock()
    resp.json.return_value = {"tag_name": "v0.5.0"}
    with patch("illusion_forge.commands.misc.httpx.get", return_value=resp):
        assert _check_latest_release() == "0.5.0"


def test_check_latest_release_returns_none_on_http_error():
    """网络/HTTP 错误时返回 None 而非抛出。"""
    import httpx

    with patch("illusion_forge.commands.misc.httpx.get", side_effect=httpx.ConnectError("boom")):
        assert _check_latest_release() is None
