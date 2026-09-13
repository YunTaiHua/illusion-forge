"""
认证相关斜杠命令
================

/login, /logout
"""

from __future__ import annotations

from illusion_forge.api.auth_status import auth_status
from illusion_forge.auth.storage import clear_env_credentials
from illusion_forge.commands.types import CommandContext, CommandResult
from illusion_forge.config.settings import load_settings, save_settings


async def login_handler(args: str, context: CommandContext) -> CommandResult:
    """显示认证状态或存储 API Key / Auth Token"""
    del context
    settings = load_settings()
    env = settings._active_env
    credential = args.strip()
    if not credential:
        current_key = env.api_key or env.auth_token or ""
        masked = (
            f"{current_key[:6]}...{current_key[-4:]}"
            if current_key
            else "(not configured)"
        )
        auth_type = "auth_token" if env.auth_token else "api_key"
        return CommandResult(
            message=(
                f"Auth status:\n"
                f"- auth_status: {auth_status(settings)}\n"
                f"- base_url: {settings.base_url or '(default)'}\n"
                f"- model: {settings.model}\n"
                f"- {auth_type}: {masked}\n"
                "\nUsage:\n"
                "  /login API_KEY          (standard x-api-key auth)\n"
                "  /login auth_token TOKEN (Bearer Token auth)"
            )
        )
    env_key = settings._active_env_key
    # 检查是否是 auth_token 格式：login auth_token <token>
    if credential.startswith("auth_token "):
        token = credential[11:].strip()
        updated_env = env.model_copy(update={"auth_token": token, "api_key": ""})
        msg = "Stored auth_token in ~/.illusion/settings.json"
    else:
        updated_env = env.model_copy(update={"api_key": credential, "auth_token": ""})
        msg = "Stored API key in ~/.illusion/settings.json"
    setattr(settings, env_key, updated_env)
    save_settings(settings)
    return CommandResult(message=msg)


async def logout_handler(_: str, context: CommandContext) -> CommandResult:
    """清除已存储的 API Key / Auth Token"""
    del context
    settings = load_settings()
    env_key = settings._active_env_key
    env = settings._active_env
    updated_env = env.model_copy(update={"api_key": "", "auth_token": ""})
    setattr(settings, env_key, updated_env)
    save_settings(settings)
    # 清除 credentials.json 中的密钥
    clear_env_credentials(env_key)
    return CommandResult(message="Cleared stored API key and auth token.")
