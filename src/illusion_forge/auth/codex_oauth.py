"""
OpenAI Codex OAuth 认证模块
============================

本模块提供 OpenAI ChatGPT Plus/Pro 订阅的 OAuth Device Code 认证流程。

认证流程：
    1. 启动 Device Code 流程，获取 device_auth_id 和 user_code
    2. 用户在浏览器中完成 ChatGPT 授权
    3. 轮询获取 authorization_code 和 code_verifier
    4. 使用 code + verifier 换取 access_token + refresh_token + id_token
    5. 自动刷新 access_token（到期前 60 秒）

存储格式：
    ~/.illusion/codex_oauth_auth.json

使用示例：
    >>> from illusion_forge.auth.codex_oauth import CodexOAuth
    >>> auth = CodexOAuth()
    >>> flow = auth.start_device_flow()
    >>> print(f"请在浏览器中访问: {flow['verification_uri']}")
    >>> print(f"输入代码: {flow['user_code']}")
    >>> auth.poll_for_token(flow['device_code'])
    >>> token = auth.get_valid_token()
"""

from __future__ import annotations

import base64
import json
import logging
import platform
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from illusion_forge.config.paths import get_config_dir

# 模块级日志记录器
log = logging.getLogger(__name__)

# OpenAI OAuth 客户端 ID（与官方 Codex CLI 相同）
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

# OpenAI 端点
_DEVICE_AUTH_USERCODE_URL = "https://auth.openai.com/api/accounts/deviceauth/usercode"
_DEVICE_AUTH_TOKEN_URL = "https://auth.openai.com/api/accounts/deviceauth/token"
_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
_DEVICE_VERIFICATION_URL = "https://auth.openai.com/codex/device"
_DEVICE_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"

# JWT 声明路径
JWT_CLAIM_PATH = "https://api.openai.com/auth"

# Token 刷新提前量（秒）
_TOKEN_REFRESH_BUFFER = 60

# 轮询默认间隔和超时
_POLL_INTERVAL = 5
_POLL_TIMEOUT = 900  # 15 分钟

# User-Agent
_CODEX_USER_AGENT = f"illusion-forge ({platform.system().lower()} {platform.machine() or 'unknown'})"


def _request_json(
    url: str,
    *,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """发送 HTTP 请求并返回 JSON 响应

    Args:
        url: 请求 URL
        method: HTTP 方法
        data: 表单数据
        json_data: JSON 数据
        headers: 请求头
        timeout: 超时时间（秒）

    Returns:
        dict[str, Any]: JSON 响应
    """
    req_headers = {
        "Accept": "application/json",
        "User-Agent": _CODEX_USER_AGENT,
    }
    if headers:
        req_headers.update(headers)

    body = None
    if json_data:
        body = json.dumps(json_data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    elif data:
        body = urllib.parse.urlencode(data).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        return result


def _extract_account_id(token: str) -> str:
    """从 JWT token 中提取 chatgpt_account_id

    Args:
        token: JWT 访问令牌

    Returns:
        str: 账户 ID，提取失败时返回空字符串
    """
    parts = token.split(".")
    if len(parts) != 3:
        return ""
    try:
        encoded = parts[1]
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ""
    auth = payload.get(JWT_CLAIM_PATH)
    if isinstance(auth, dict):
        return str(auth.get("chatgpt_account_id", "") or "")
    return ""


def _extract_identity_from_tokens(
    access_token: str,
    id_token: str | None = None,
) -> tuple[str | None, str | None]:
    """从 token 中提取 (account_id, email)

    Args:
        access_token: 访问令牌
        id_token: ID 令牌（可选）

    Returns:
        tuple[str | None, str | None]: (account_id, email)
    """
    account_id: str | None = None
    email: str | None = None

    # 优先从 id_token 提取
    if id_token:
        parts = id_token.split(".")
        if len(parts) == 3:
            try:
                encoded = parts[1]
                padded = encoded + "=" * (-len(encoded) % 4)
                payload = json.loads(
                    base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
                )
                # 尝试多种路径获取 account_id
                account_id = (
                    payload.get("chatgpt_account_id")
                    or (payload.get("https://api.openai.com/auth") or {}).get(
                        "chatgpt_account_id"
                    )
                    or (payload.get("organizations", [{}])[0].get("id") if payload.get("organizations") else None)
                )
                email = payload.get("email")
            except (ValueError, UnicodeDecodeError) as exc:
                log.debug("解析 id_token 失败: %s", exc)

    # 回退到 access_token
    if not account_id:
        account_id = _extract_account_id(access_token)

    return account_id, email


@dataclass
class CodexAccountData:
    """Codex 账号数据

    Attributes:
        account_id: chatgpt_account_id
        email: 账号邮箱（如果可获取）
        refresh_token: Refresh Token（持久化）
        authenticated_at: 认证时间戳（秒）
    """

    account_id: str = ""
    email: str | None = None
    refresh_token: str = ""
    authenticated_at: int = 0


@dataclass
class CodexOAuthData:
    """Codex OAuth 认证数据

    Attributes:
        accounts: 账号列表
        default_account_id: 默认账号 ID
        access_tokens: 内存缓存的 access_token（不持久化）
    """

    accounts: list[CodexAccountData] = field(default_factory=list[Any])
    default_account_id: str | None = None
    # 运行时缓存，不持久化
    access_tokens: dict[str, tuple[str, float]] = field(default_factory=dict[str, Any])


class CodexOAuth:
    """OpenAI Codex OAuth 认证管理器

    管理 OpenAI Device Code 流程和 access_token 的获取、刷新、持久化。
    """

    def __init__(self) -> None:
        self._storage_path = get_config_dir() / "codex_oauth_auth.json"
        self._data = self._load()

    @property
    def storage_path(self) -> Path:
        """返回存储文件路径"""
        return self._storage_path

    def _load(self) -> CodexOAuthData:
        """从磁盘加载认证数据

        Returns:
            CodexOAuthData: 认证数据
        """
        if not self._storage_path.exists():
            return CodexOAuthData()
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
            accounts = [
                CodexAccountData(
                    account_id=a.get("account_id", ""),
                    email=a.get("email"),
                    refresh_token=a.get("refresh_token", ""),
                    authenticated_at=a.get("authenticated_at", 0),
                )
                for a in raw.get("accounts", [])
            ]
            return CodexOAuthData(
                accounts=accounts,
                default_account_id=raw.get("default_account_id"),
            )
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("加载 Codex OAuth 认证数据失败: %s", exc)
            return CodexOAuthData()

    def _save(self) -> None:
        """保存认证数据到磁盘"""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "accounts": [
                {
                    "account_id": a.account_id,
                    "email": a.email,
                    "refresh_token": a.refresh_token,
                    "authenticated_at": a.authenticated_at,
                }
                for a in self._data.accounts
            ],
            "default_account_id": self._data.default_account_id,
        }
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
        return len(self._data.accounts) > 0

    def get_status(self) -> dict[str, Any]:
        """获取认证状态

        Returns:
            dict[str, Any]: 认证状态信息
        """
        accounts = []
        for a in self._data.accounts:
            accounts.append({
                "id": a.account_id,
                "login": a.email or f"ChatGPT ({a.account_id[:8]}...)",
                "authenticated_at": a.authenticated_at,
            })
        return {
            "authenticated": self.is_authenticated(),
            "username": self._get_username(),
            "default_account_id": self._data.default_account_id,
            "accounts": accounts,
        }

    def _get_username(self) -> str | None:
        """获取默认账号的用户名

        Returns:
            str | None: 用户名
        """
        if not self._data.accounts:
            return None
        # 优先返回默认账号
        if self._data.default_account_id:
            for a in self._data.accounts:
                if a.account_id == self._data.default_account_id:
                    return a.email or f"ChatGPT ({a.account_id[:8]}...)"
        # 回退到第一个账号
        first = self._data.accounts[0]
        return first.email or f"ChatGPT ({first.account_id[:8]}...)"

    def start_device_flow(self) -> dict[str, Any]:
        """启动 OpenAI Device Code 流程

        Returns:
            dict[str, Any]: 包含 device_code、user_code、verification_uri 的字典

        Raises:
            RuntimeError: 设备码请求失败
        """
        log.info("启动 Codex Device Code 流程")
        try:
            data = _request_json(
                _DEVICE_AUTH_USERCODE_URL,
                method="POST",
                json_data={"client_id": CODEX_CLIENT_ID},
            )
        except Exception as exc:
            log.error("Device Code 请求失败: %s", exc)
            raise RuntimeError(f"Device Code 请求失败: {exc}") from exc

        device_auth_id = data.get("device_auth_id", "")
        user_code = data.get("user_code", "")
        expires_in = int(data.get("expires_in", 900))
        interval = int(data.get("interval", 5))

        log.info("获取 Device Code 成功，user_code: %s", user_code)

        return {
            "device_code": device_auth_id,
            "user_code": user_code,
            "verification_uri": _DEVICE_VERIFICATION_URL,
            "expires_in": expires_in,
            "interval": interval + 3,  # 添加安全余量
        }

    def poll_for_token(self, device_code: str) -> bool:
        """轮询 Device Code 状态，等待用户完成授权

        Args:
            device_code: device_auth_id

        Returns:
            bool: 是否授权成功

        Raises:
            RuntimeError: 授权被拒绝或设备码过期
        """
        log.info("开始轮询 Codex Device Code")
        start_time = time.time()

        while time.time() - start_time < _POLL_TIMEOUT:
            try:
                data = _request_json(
                    _DEVICE_AUTH_TOKEN_URL,
                    method="POST",
                    json_data={
                        "device_auth_id": device_code,
                        "user_code": "",  # 服务端会通过 device_auth_id 关联
                    },
                )
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 404):
                    # 用户未完成授权，继续轮询
                    time.sleep(_POLL_INTERVAL)
                    continue
                if exc.code == 410:
                    raise RuntimeError("设备码已过期，请重新运行登录") from exc
                log.warning("轮询请求失败: %s", exc)
                time.sleep(_POLL_INTERVAL)
                continue
            except (urllib.error.URLError, OSError, ValueError) as exc:
                log.warning("轮询请求失败: %s", exc)
                time.sleep(_POLL_INTERVAL)
                continue

            # 检查是否获取到 authorization_code
            authorization_code = data.get("authorization_code")
            code_verifier = data.get("code_verifier")

            if authorization_code and code_verifier:
                log.info("用户已授权，正在换取 OAuth Token")
                self._exchange_code_for_tokens(authorization_code, code_verifier)
                return True

            time.sleep(_POLL_INTERVAL)

        raise RuntimeError("设备码轮询超时")

    def _exchange_code_for_tokens(self, code: str, code_verifier: str) -> None:
        """用 authorization_code + code_verifier 换取 tokens

        Args:
            code: 授权码
            code_verifier: 代码验证器

        Raises:
            RuntimeError: Token 交换失败
        """
        try:
            data = _request_json(
                _OAUTH_TOKEN_URL,
                method="POST",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _DEVICE_REDIRECT_URI,
                    "client_id": CODEX_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
            )
        except Exception as exc:
            raise RuntimeError(f"Token 交换失败: {exc}") from exc

        access_token = data.get("access_token", "")
        refresh_token = data.get("refresh_token", "")
        id_token = data.get("id_token")

        if not access_token:
            raise RuntimeError("Token 响应中缺少 access_token")

        # 提取账号信息
        account_id, email = _extract_identity_from_tokens(access_token, id_token)
        if not account_id:
            raise RuntimeError("无法从 token 中提取 account_id")

        # 计算过期时间
        expires_in = int(data.get("expires_in", 3600))
        expires_at = time.time() + expires_in

        # 缓存 access_token
        self._data.access_tokens[account_id] = (access_token, expires_at)

        # 添加或更新账号
        self._add_account(account_id, refresh_token, email)

        log.info("Codex OAuth 认证完成，账号: %s", account_id)

    def _add_account(self, account_id: str, refresh_token: str, email: str | None = None) -> None:
        """添加或更新账号

        Args:
            account_id: 账号 ID
            refresh_token: 刷新令牌
            email: 邮箱
        """
        now = int(time.time())

        # 查找现有账号
        for i, a in enumerate(self._data.accounts):
            if a.account_id == account_id:
                # 更新现有账号
                self._data.accounts[i] = CodexAccountData(
                    account_id=account_id,
                    email=email or a.email,
                    refresh_token=refresh_token or a.refresh_token,
                    authenticated_at=now,
                )
                break
        else:
            # 添加新账号
            self._data.accounts.append(
                CodexAccountData(
                    account_id=account_id,
                    email=email,
                    refresh_token=refresh_token,
                    authenticated_at=now,
                )
            )

        # 设置默认账号
        if not self._data.default_account_id:
            self._data.default_account_id = account_id

        self._save()

    def _refresh_token(self, account_id: str) -> str:
        """用 refresh_token 刷新 access_token

        Args:
            account_id: 账号 ID

        Returns:
            str: 新的 access_token

        Raises:
            RuntimeError: 刷新失败
        """
        # 查找账号
        account = None
        for a in self._data.accounts:
            if a.account_id == account_id:
                account = a
                break

        if not account or not account.refresh_token:
            raise RuntimeError(f"账号 {account_id} 无 refresh_token")

        log.info("刷新账号 %s 的 access_token", account_id)

        try:
            data = _request_json(
                _OAUTH_TOKEN_URL,
                method="POST",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": account.refresh_token,
                    "client_id": CODEX_CLIENT_ID,
                    "scope": "openid profile email",
                },
            )
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError("Refresh Token 失效或已过期") from exc
            raise RuntimeError(f"Refresh Token 失败: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"Refresh Token 失败: {exc}") from exc

        access_token = data.get("access_token", "")
        new_refresh_token = data.get("refresh_token", "")
        expires_in = int(data.get("expires_in", 3600))

        if not access_token:
            raise RuntimeError("Refresh 响应中缺少 access_token")

        # 更新 refresh_token（如果服务端返回了新的）
        if new_refresh_token and new_refresh_token != account.refresh_token:
            account.refresh_token = new_refresh_token
            self._save()

        # 缓存 access_token
        expires_at = time.time() + expires_in
        self._data.access_tokens[account_id] = (access_token, expires_at)

        return str(access_token)

    def get_valid_token(self, account_id: str | None = None) -> str:
        """获取有效的 access_token，自动刷新

        Args:
            account_id: 账号 ID，默认使用默认账号

        Returns:
            str: 有效的 access_token

        Raises:
            RuntimeError: 未认证或刷新失败
        """
        if not self._data.accounts:
            raise RuntimeError("未认证，请先运行 'illusion-forge auth login' 选择 Codex")

        # 确定账号 ID
        if not account_id:
            account_id = self._data.default_account_id
        if not account_id:
            account_id = self._data.accounts[0].account_id

        # 检查缓存
        cached = self._data.access_tokens.get(account_id)
        if cached:
            token, expires_at = cached
            if expires_at - time.time() > _TOKEN_REFRESH_BUFFER:
                return token

        # 刷新 token
        return self._refresh_token(account_id)

    def remove_account(self, account_id: str) -> None:
        """移除账号

        Args:
            account_id: 账号 ID
        """
        self._data.accounts = [a for a in self._data.accounts if a.account_id != account_id]
        self._data.access_tokens.pop(account_id, None)

        # 更新默认账号
        if self._data.default_account_id == account_id:
            self._data.default_account_id = (
                self._data.accounts[0].account_id if self._data.accounts else None
            )

        self._save()
        log.info("已移除账号: %s", account_id)

    def set_default_account(self, account_id: str) -> None:
        """设置默认账号

        Args:
            account_id: 账号 ID

        Raises:
            ValueError: 账号不存在
        """
        for a in self._data.accounts:
            if a.account_id == account_id:
                self._data.default_account_id = account_id
                self._save()
                return
        raise ValueError(f"账号不存在: {account_id}")

    def clear_auth(self) -> None:
        """清除所有认证数据"""
        self._data = CodexOAuthData()
        if self._storage_path.exists():
            try:
                self._storage_path.unlink()
            except OSError:
                pass
        log.info("Codex OAuth 认证已清除")
