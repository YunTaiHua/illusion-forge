"""
模型管理斜杠命令
================

/model — 显示或切换模型

模型以对象格式声明在 settings.json 中：
    "env_1": { "model_1": { "name": "gpt-4o", "capabilities": ["image"] } }

`/model set` 只切换当前模型；媒体能力沿用 settings.json 中已声明的值，
由 Web 设置面板维护。
"""

from __future__ import annotations

from illusion_forge.commands.types import CommandContext, CommandResult
from illusion_forge.config.capabilities import ModelCapabilities
from illusion_forge.config.settings import Settings, load_settings, save_settings

_MODEL_OBJECT_KEY_HINT = (
    'model must be declared as an object: '
    '"{model_key}": {{"name": "<model name>", "capabilities": ["image"]}}'
)


def _capabilities_text(capabilities: ModelCapabilities | list[str]) -> str:
    """能力显示文案：ModelCapabilities/列表 → "image" / "none"。"""
    if isinstance(capabilities, ModelCapabilities):
        names = ["image"] if capabilities.supports_images else []
    else:
        names = list(capabilities or [])
    return ", ".join(names) if names else "none"


def _describe_models(settings: Settings) -> str:
    """汇总所有 env 的模型（含能力）供 /model list 显示。"""
    lines = []
    for env_key, env in settings.list_envs().items():
        for model_key, config in env.list_model_configs().items():
            ref = f"{env_key}.{model_key}"
            active = " (active)" if ref == settings.model else ""
            caps = _capabilities_text(config.capabilities)
            lines.append(f"  {ref}{active}: {config.name} [{caps}] ({env.api_format})")
    return "\n".join(lines)


async def model_handler(args: str, context: CommandContext) -> CommandResult:
    """模型管理命令处理器"""
    from illusion_forge.config.i18n import t as i18n_t
    settings = load_settings()
    tokens = args.split(maxsplit=1)
    if not tokens or tokens[0] == "show":
        env = settings._active_env
        caps = _capabilities_text(settings.get_model_capabilities())
        return CommandResult(
            message=i18n_t("model_active", model=settings.model) + "\n" +
                    i18n_t("model_env_model", name=settings.active_model_name) + "\n" +
                    i18n_t("model_api_format", fmt=env.api_format) + "\n" +
                    i18n_t("model_base_url", url=env.base_url or i18n_t("model_default_url")) + "\n" +
                    i18n_t("model_capabilities", caps=caps)
        )
    if tokens[0] == "list":
        return CommandResult(
            message=i18n_t("model_list_title") + "\n" + _describe_models(settings)
        )
    # 切换模型
    model_ref = tokens[0] if tokens[0] != "set" else (tokens[1] if len(tokens) > 1 else "")
    return await _set_model(model_ref, settings, context)


async def _set_model(
    model_ref: str,
    settings: Settings,
    context: CommandContext,
) -> CommandResult:
    """切换模型并（终端交互时）确认图片能力。"""
    from illusion_forge.config.i18n import t as i18n_t
    if "." not in model_ref:
        return CommandResult(message=i18n_t("model_unknown", ref=model_ref))

    env_key, model_key = model_ref.split(".", 1)
    env = settings.get_env(env_key)
    if env is None:
        return CommandResult(message=i18n_t("model_unknown", ref=model_ref))

    model_config = env.get_model_config(model_key)
    if model_config is None:
        return CommandResult(
            message=(
                f"Model {model_ref} is not a valid model object. {_MODEL_OBJECT_KEY_HINT}"
            )
        )

    # 媒体能力沿用 settings.json 已声明值（由 Web 设置面板维护）
    caps_text = _capabilities_text(model_config.capabilities)
    old_env_key = settings._active_env_key
    settings.model = model_ref
    save_settings(settings)
    context.engine.set_model(model_config.name)
    if context.app_state is not None:
        context.app_state.set(model=model_config.name)
    needs_rebuild = env_key != old_env_key
    # 通知渠道守护进程重新加载 settings.json
    # 守护进程启动时对 settings.json 做一次性快照，切换 env 后必须刷新
    if needs_rebuild:
        try:
            from illusion_forge.daemon_ipc import notify_channel_daemon_reload
            notify_channel_daemon_reload()
        except (ImportError, OSError, RuntimeError):
            pass  # 守护进程未运行或通知失败，静默忽略
    return CommandResult(
        message=i18n_t("model_set_to", ref=model_ref, name=model_config.name)
        + "\n" + i18n_t("model_capabilities", caps=caps_text),
        needs_api_rebuild=needs_rebuild,
    )
