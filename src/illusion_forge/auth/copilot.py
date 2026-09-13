"""
GitHub Copilot OAuth 认证模块
============================

本模块提供 GitHub Copilot OAuth 设备码认证流程。

认证流程：
    1. 启动设备码流程，获取 device_code 和 user_code
    2. 用户在浏览器中完成 GitHub 授权
    3. 轮询获取 GitHub access_token
    4. 使用 GitHub token 获取 Copilot token
    5. 自动刷新 Copilot token（到期前刷新）

存储格式：
    ~/.illusion/copilot_auth.json

使用示例：
    >>> from illusion_forge.auth.copilot import CopilotAuth
    >>> auth = CopilotAuth()
    >>> flow = auth.start_device_flow()
    >>> print(f"请在浏览器中访问: {flow['verification_uri']}")
    >>> print(f"输入代码: {flow['user_code']}")
    >>> auth.poll_for_token(flow['device_code'])
    >>> token = auth.get_valid_token()
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from illusion_forge.config.paths import get_config_dir

# 模块级日志记录器
log = logging.getLogger(__name__)

# GitHub OAuth 客户端 ID（VS Code Copilot 扩展使用的公开 ID）
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"

# Copilot API 常量
COPILOT_API_BASE = "https://api.githubcopilot.com"
COPILOT_EDITOR_VERSION = "vscode/1.110.1"
COPILOT_PLUGIN_VERSION = "copilot-chat/0.38.2"
COPILOT_USER_AGENT = "GitHubCopilotChat/0.38.2"
COPILOT_API_VERSION = "2025-10-01"
COPILOT_INTEGRATION_ID = "vscode-chat"

# GitHub 端点
_GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
_GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"

# Token 刷新提前量（秒）：在 refresh_in 推荐间隔前提前刷新，留出缓冲
_TOKEN_REFRESH_BUFFER = 60

# 轮询默认间隔和超时
_POLL_INTERVAL = 5
_POLL_TIMEOUT = 900  # 15 分钟


def _request_json(
    url: str,
    *,
    method: str = "GET",
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    """发送 HTTP 请求并返回 JSON 响应

    Args:
        url: 请求 URL
        method: HTTP 方法
        data: 表单数据
        headers: 请求头
        timeout: 超时时间（秒）

    Returns:
        dict[str, Any]: JSON 响应
    """
    req_headers = {
        "Accept": "application/json",
        "User-Agent": COPILOT_USER_AGENT,
    }
    if headers:
        req_headers.update(headers)

    body = None
    if data:
        body = urllib.parse.urlencode(data).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        return result


def copilot_api_headers(token: str) -> dict[str, str]:
    """返回 Copilot API 请求所需的特殊请求头

    Args:
        token: Copilot token

    Returns:
        dict[str, str]: 请求头字典
    """
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "copilot-integration-id": COPILOT_INTEGRATION_ID,
        "editor-version": COPILOT_EDITOR_VERSION,
        "editor-plugin-version": COPILOT_PLUGIN_VERSION,
        "user-agent": COPILOT_USER_AGENT,
        "x-github-api-version": COPILOT_API_VERSION,
    }


def copilot_extra_headers() -> dict[str, str]:
    """返回创建 OpenAI 客户端时需注入的额外请求头（不含 Authorization）

    Returns:
        dict[str, str]: 额外请求头字典
    """
    return {
        "copilot-integration-id": COPILOT_INTEGRATION_ID,
        "editor-version": COPILOT_EDITOR_VERSION,
        "editor-plugin-version": COPILOT_PLUGIN_VERSION,
        "user-agent": COPILOT_USER_AGENT,
        "x-github-api-version": COPILOT_API_VERSION,
    }


@dataclass
class CopilotAuthData:
    """Copilot 认证数据

    Attributes:
        github_token: GitHub OAuth access token
        copilot_token: Copilot token（JWT）
        copilot_token_expires_at: Copilot token 过期时间（Unix 秒）
        copilot_token_refresh_at: Copilot token 推荐刷新时间点（Unix 秒）
        user_login: GitHub 用户名
        user_id: GitHub 用户 ID
        authenticated_at: 认证时间戳
    """

    github_token: str = ""
    copilot_token: str = ""
    copilot_token_expires_at: int = 0
    copilot_token_refresh_at: int = 0
    user_login: str = ""
    user_id: int = 0
    authenticated_at: int = 0


class CopilotAuth:
    """GitHub Copilot OAuth 认证管理器

    管理 GitHub OAuth 设备码流程和 Copilot token 的获取、刷新、持久化。
    """

    def __init__(self) -> None:
        self._storage_path = get_config_dir() / "copilot_auth.json"
        self._data = self._load()

    @property
    def storage_path(self) -> Path:
        """返回存储文件路径"""
        return self._storage_path

    def _load(self) -> CopilotAuthData:
        """从磁盘加载认证数据

        Returns:
            CopilotAuthData: 认证数据
        """
        if not self._storage_path.exists():
            return CopilotAuthData()
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
            return CopilotAuthData(
                github_token=raw.get("github_token", ""),
                copilot_token=raw.get("copilot_token", ""),
                copilot_token_expires_at=raw.get("copilot_token_expires_at", 0),
                copilot_token_refresh_at=raw.get("copilot_token_refresh_at", 0),
                user_login=raw.get("user_login", ""),
                user_id=raw.get("user_id", 0),
                authenticated_at=raw.get("authenticated_at", 0),
            )
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("加载 Copilot 认证数据失败: %s", exc)
            return CopilotAuthData()

    def _save(self) -> None:
        """保存认证数据到磁盘"""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self._data)
        self._storage_path.write_text(
            json.dumps(data, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            self._storage_path.chmod(0o600)
        except OSError:
            pass

    def is_authenticated(self) -> bool:
        """检查是否已认证

        Returns:
            bool: 是否已认证
        """
        return bool(self._data.github_token)

    def get_status(self) -> dict[str, Any]:
        """获取认证状态

        Returns:
            dict[str, Any]: 认证状态信息
        """
        return {
            "authenticated": self.is_authenticated(),
            "username": self._data.user_login or None,
            "expires_at": self._data.copilot_token_expires_at or None,
        }

    def start_device_flow(self) -> dict[str, Any]:
        """启动 GitHub OAuth 设备码流程

        Returns:
            dict[str, Any]: 包含 device_code、user_code、verification_uri 的字典

        Raises:
            RuntimeError: 设备码请求失败
        """
        log.info("启动 Copilot 设备码流程")
        data = _request_json(
            _GITHUB_DEVICE_CODE_URL,
            method="POST",
            data={
                "client_id": GITHUB_CLIENT_ID,
                "scope": "read:user",
            },
        )
        log.info("获取设备码成功，user_code: %s", data.get("user_code"))
        return {
            "device_code": data["device_code"],
            "user_code": data["user_code"],
            "verification_uri": data["verification_uri"],
            "expires_in": data.get("expires_in", 900),
            "interval": data.get("interval", 5),
        }

    def poll_for_token(self, device_code: str) -> bool:
        """轮询 GitHub OAuth Token，等待用户完成授权

        Args:
            device_code: 设备码

        Returns:
            bool: 是否授权成功

        Raises:
            RuntimeError: 授权被拒绝或设备码过期
        """
        log.info("开始轮询 OAuth Token")
        start_time = time.time()

        while time.time() - start_time < _POLL_TIMEOUT:
            try:
                data = _request_json(
                    _GITHUB_OAUTH_TOKEN_URL,
                    method="POST",
                    data={
                        "client_id": GITHUB_CLIENT_ID,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                )
            except (urllib.error.URLError, ValueError) as exc:
                log.warning("轮询请求失败: %s", exc)
                time.sleep(_POLL_INTERVAL)
                continue

            error = data.get("error")
            if error == "authorization_pending":
                time.sleep(_POLL_INTERVAL)
                continue
            if error == "slow_down":
                time.sleep(_POLL_INTERVAL + 5)
                continue
            if error == "expired_token":
                raise RuntimeError("设备码已过期，请重新运行登录")
            if error == "access_denied":
                raise RuntimeError("授权被拒绝")
            if error:
                raise RuntimeError(f"OAuth 错误: {error}")

            access_token = data.get("access_token", "")
            if not access_token:
                time.sleep(_POLL_INTERVAL)
                continue

            log.info("GitHub OAuth Token 获取成功")
            self._complete_auth(access_token)
            return True

        raise RuntimeError("设备码轮询超时")

    def _complete_auth(self, github_token: str) -> None:
        """使用 GitHub token 完成认证流程

        Args:
            github_token: GitHub OAuth access token

        Raises:
            RuntimeError: Copilot 订阅验证失败
        """
        # 获取用户信息
        user_data = _request_json(
            _GITHUB_USER_URL,
            headers={
                "Authorization": f"token {github_token}",
                "Editor-Version": COPILOT_EDITOR_VERSION,
                "Editor-Plugin-Version": COPILOT_PLUGIN_VERSION,
            },
        )

        # 获取 Copilot token
        self._fetch_copilot_token(github_token)

        self._data.github_token = github_token
        self._data.user_login = user_data.get("login", "")
        self._data.user_id = user_data.get("id", 0)
        self._data.authenticated_at = int(time.time())
        self._save()
        log.info("Copilot 认证完成，用户: %s", self._data.user_login)

    def _fetch_copilot_token(self, github_token: str | None = None) -> str:
        """使用 GitHub token 获取 Copilot token

        Args:
            github_token: GitHub token，默认使用已存储的

        Returns:
            str: Copilot token

        Raises:
            RuntimeError: 获取失败
        """
        token = github_token or self._data.github_token
        if not token:
            raise RuntimeError("无 GitHub token")

        try:
            data = _request_json(
                _COPILOT_TOKEN_URL,
                headers={
                    "Authorization": f"token {token}",
                    "User-Agent": COPILOT_USER_AGENT,
                    "Editor-Version": COPILOT_EDITOR_VERSION,
                    "Editor-Plugin-Version": COPILOT_PLUGIN_VERSION,
                },
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise RuntimeError("GitHub token 无效或已过期") from exc
            if exc.code == 403:
                raise RuntimeError("未订阅 GitHub Copilot") from exc
            raise RuntimeError(f"获取 Copilot token 失败: {exc}") from exc

        copilot_token = data.get("token", "")
        expires_at = data.get("expires_at", 0)
        refresh_in = data.get("refresh_in", 0)
        if not copilot_token or not expires_at or refresh_in <= 0:
            raise RuntimeError("Copilot token 响应字段不完整")

        # 在 refresh_in 推荐间隔前提前刷新，留出缓冲
        refresh_at = int(time.time()) + refresh_in - _TOKEN_REFRESH_BUFFER

        self._data.copilot_token = copilot_token
        self._data.copilot_token_expires_at = expires_at
        self._data.copilot_token_refresh_at = refresh_at
        if github_token:
            self._data.github_token = github_token
        self._save()
        log.info(
            "Copilot Token 获取成功，过期时间: %s，刷新时间: %s",
            expires_at,
            refresh_at,
        )
        return str(copilot_token)

    def get_valid_token(self) -> str:
        """获取有效的 Copilot token，自动刷新

        基于 refresh_at 推荐刷新时间点判断是否需要刷新：
        - 无 copilot_token 或已到 refresh_at，触发刷新
        - 未到 refresh_at，返回缓存 token（滚动续期，token 始终远离过期）

        Returns:
            str: 有效的 Copilot token

        Raises:
            RuntimeError: 未认证或刷新失败
        """
        if not self._data.github_token:
            raise RuntimeError("未认证，请先运行 'illusion-forge auth login' 选择 GitHub Copilot")

        now = int(time.time())
        if self._data.copilot_token and now < self._data.copilot_token_refresh_at:
            return self._data.copilot_token

        log.info("Copilot Token 需要刷新")
        return self._fetch_copilot_token()

    def clear_auth(self) -> None:
        """清除所有认证数据"""
        self._data = CopilotAuthData()
        if self._storage_path.exists():
            try:
                self._storage_path.unlink()
            except OSError:
                pass
        log.info("Copilot 认证已清除")
