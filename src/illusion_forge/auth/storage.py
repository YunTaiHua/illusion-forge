"""
安全凭据存储模块
================

本模块为 IllusionForge 提供安全的凭据存储功能。

默认后端：~/.illusion/credentials.json，权限 600

函数说明：
    - store_env_credential/load_env_credential: 按 env_N 分组存取凭据
    - clear_env_credentials: 清除指定环境的凭据
    - encrypt/decrypt: 轻量级混淆加密

使用示例：
    >>> from illusion_forge.auth.storage import store_env_credential, load_env_credential
    >>> store_env_credential("env_1", "api_key", "sk-...")
    >>> key = load_env_credential("env_1", "api_key")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from illusion_forge.config.paths import get_config_dir

# 模块级日志记录器
log = logging.getLogger(__name__)

# 常量定义
_CREDS_FILE_NAME = "credentials.json"  # 凭据文件名
_KEYRING_SERVICE = "illusion"  # keyring 服务名


# ---------------------------------------------------------------------------
# 文件后端（始终可用）
# ---------------------------------------------------------------------------


def _creds_path() -> Path:
    """获取凭据文件路径"""
    return get_config_dir() / _CREDS_FILE_NAME


def _load_creds_file() -> dict[str, Any]:
    """加载凭据文件
    
    Returns:
        dict[str, Any]: 凭据数据字典
    """
    path = _creds_path()
    if not path.exists():
        return {}
    try:
        result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return result
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to read credentials file: %s", exc)
        return {}


def _save_creds_file(data: dict[str, Any]) -> None:
    """保存凭据文件
    
    Args:
        data: 凭据数据字典
    """
    path = _creds_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# env_N 凭据存储（按环境分组）
# ---------------------------------------------------------------------------


def store_env_credential(env_key: str, key: str, value: str) -> None:
    """按 env_N 分组存储凭据

    Args:
        env_key: 环境键名（如 "env_1"）
        key: 键名（如 "api_key"）
        value: 凭据值
    """
    data = _load_creds_file()
    data.setdefault(env_key, {})[key] = value
    _save_creds_file(data)
    log.debug("Stored %s/%s in credentials file (env)", env_key, key)


def load_env_credential(env_key: str, key: str) -> str | None:
    """按 env_N 读取凭据，未找到返回 None

    Args:
        env_key: 环境键名（如 "env_1"）
        key: 键名（如 "api_key"）

    Returns:
        str | None: 凭据值或 None
    """
    data = _load_creds_file()
    value: str | None = data.get(env_key, {}).get(key)
    return value


def clear_env_credentials(env_key: str) -> None:
    """删除 env_N 的所有存储凭据

    Args:
        env_key: 环境键名（如 "env_1"）
    """
    data = _load_creds_file()
    if env_key in data:
        del data[env_key]
        _save_creds_file(data)
    log.debug("Cleared credentials for env: %s", env_key)


# ---------------------------------------------------------------------------
# 加密/解密辅助函数（轻量级 XOR 混淆，非真正加密）
# ---------------------------------------------------------------------------


def _obfuscation_key() -> bytes:
    """返回从主目录路径派生的每用户混淆密钥
    
    Returns:
        bytes: 32 字节混淆密钥
    """
    seed = str(Path.home()).encode() + b"illusion-v1"
    # 通过 SHA-256 简单重复密钥拉伸到 32 字节以保持确定性
    import hashlib

    return hashlib.sha256(seed).digest()


def encrypt(plaintext: str) -> str:
    """轻量级混淆 plaintext（base64 编码 XOR）。非加密。
    
    Args:
        plaintext: 明文
    
    Returns:
        str: 混淆后的字符串
    """
    import base64

    key = _obfuscation_key()
    data = plaintext.encode("utf-8")
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.urlsafe_b64encode(xored).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """encrypt 的反向操作
    
    Args:
        ciphertext: 混淆的字符串
    
    Returns:
        str: 明文
    """
    import base64

    key = _obfuscation_key()
    data = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return xored.decode("utf-8")
