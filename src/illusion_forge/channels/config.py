"""渠道配置模型与读写
====================

本模块定义各消息渠道的配置模型，以及 channels.json 的加载/保存。

配置存储于 ~/.illusion/channels.json，与主 settings.json 分离。
顶层 key 为渠道名（feishu）

类说明：
    - FeishuGroupPolicy: 飞书群组访问策略
    - FeishuChannelConfig: 飞书渠道配置
    - ChannelsConfig: 所有渠道配置容器

使用示例：
    >>> from illusion_forge.channels.config import load_channels_config
    >>> cfg = load_channels_config()
    >>> if cfg.feishu.enabled:
    ...     print("飞书渠道已启用")
"""
from __future__ import annotations

import json  # JSON 读写
import logging  # 日志记录
from pathlib import Path  # 路径处理

from pydantic import BaseModel, Field  # 数据模型

from illusion_forge.utils.atomic_write import atomic_write_text  # 原子写入工具

logger = logging.getLogger(__name__)  # 模块日志器


class FeishuGroupPolicy(BaseModel):
    """飞书群组访问策略

    控制机器人如何响应群组消息。

    Attributes:
        mode: 策略模式，open（全部允许）/ disabled（全部拒绝）/
              allowlist（仅白名单）/ blacklist（除黑名单外允许）
        allowlist: 允许的 chat_id 列表（mode=allowlist 时生效）
        blacklist: 拒绝的 chat_id 列表（mode=blacklist 时生效）
        admin_list: 永远放行的 user_id 列表（管理员）
    """

    mode: str = "open"  # 默认开放
    allowlist: list[str] = Field(default_factory=list)  # 白名单 chat_id
    blacklist: list[str] = Field(default_factory=list)  # 黑名单 chat_id
    admin_list: list[str] = Field(default_factory=list)  # 管理员 user_id


class FeishuChannelConfig(BaseModel):
    """飞书渠道配置

    存储飞书自建应用的凭据和行为选项。App Secret 明文存储（按需求不遮掩）。

    Attributes:
        enabled: 是否启用该渠道
        app_id: 飞书应用 App ID
        app_secret: 飞书应用 App Secret（明文）
        domain: 域名，feishu（国内）或 lark（国际）
        require_mention: 群组中是否要求 @机器人才响应
        allow_bots: 是否允许其他机器人的消息
        group_sessions_per_user: 群组会话是否按用户隔离
        group_policy: 群组访问策略
        show_reasoning: 是否在回复中显示思考过程
    """

    enabled: bool = False  # 默认未启用
    app_id: str = ""  # 应用 ID
    app_secret: str = ""  # 应用密钥（明文）
    domain: str = "feishu"  # 域名：feishu 或 lark
    require_mention: bool = True  # 群组需 @提及
    allow_bots: bool = False  # 默认拒绝机器人消息
    group_sessions_per_user: bool = True  # 群组会话按用户隔离
    group_policy: FeishuGroupPolicy = Field(default_factory=FeishuGroupPolicy)  # 群组策略
    show_reasoning: bool = True  # 默认显示思考过程
    working_directory: str | None = None  # 渠道 agent 运行目录（缺省 = 默认工作区）


class WeixinChannelConfig(BaseModel):
    """微信渠道配置

    凭据由扫码登录动态获取（account_id 形如 xxx@im.bot）。
    采用腾讯 iLink Bot API（长轮询），不是逆向 hook。

    Attributes:
        enabled: 是否启用该渠道
        account_id: iLink Bot 账号 ID（@im.bot 格式，扫码后获取）
        token: iLink Bot 鉴权 token（Bearer，扫码后获取）
        base_url: API 入口（可能因扫码重定向改变）
        cdn_base_url: 媒体传输 CDN 基础 URL（AES 加密传输）
        user_id: bot 自身 ilink user id
        allow_bots: 是否处理其他机器人的消息
    """

    enabled: bool = False  # 默认未启用
    account_id: str = ""  # @im.bot 格式
    token: str = ""  # Bearer token
    base_url: str = "https://ilinkai.weixin.qq.com"  # API 入口
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"  # CDN 入口
    user_id: str = ""  # bot 自身 user id
    allow_bots: bool = False  # 默认拒绝机器人消息
    working_directory: str | None = None  # 渠道 agent 运行目录（缺省 = 默认工作区）


class QQGroupPolicy(BaseModel):
    """QQ 群组访问策略

    控制机器人如何响应群组消息。

    Attributes:
        mode: 策略模式，open（全部允许）/ disabled（全部拒绝）/
              allowlist（仅白名单）/ blacklist（除黑名单外允许）
        allowlist: 允许的 group_openid 列表（mode=allowlist 时生效）
        blacklist: 拒绝的 group_openid 列表（mode=blacklist 时生效）
        admin_list: 永远放行的 user_openid 列表（管理员）
    """

    mode: str = "open"  # 默认开放
    allowlist: list[str] = Field(default_factory=list)  # 白名单 group_openid
    blacklist: list[str] = Field(default_factory=list)  # 黑名单 group_openid
    admin_list: list[str] = Field(default_factory=list)  # 管理员 user_openid


class QQChannelConfig(BaseModel):
    """QQ 渠道配置

    存储 QQ 开放平台机器人应用的凭据和行为选项。

    Attributes:
        enabled: 是否启用该渠道
        app_id: QQ 开放平台应用 App ID
        client_secret: QQ 开放平台应用 App Secret（明文）
        allow_bots: 是否允许其他机器人的消息
        group_sessions_per_user: 群组会话是否按用户隔离
        require_mention: 群组中是否要求 @机器人才响应
        group_policy: 群组访问策略
        markdown_support: 是否使用 markdown 渲染（msg_type=2，需申请模板权限，默认关闭）
        show_reasoning: 是否在回复中显示思考过程
    """

    enabled: bool = False  # 默认未启用
    app_id: str = ""  # 应用 ID
    client_secret: str = ""  # 应用密钥（明文）
    markdown_support: bool = False  # 是否使用 markdown 渲染（msg_type=2，需申请模板权限，默认关闭）
    allow_bots: bool = False  # 默认拒绝机器人消息
    group_sessions_per_user: bool = True  # 群组会话按用户隔离
    require_mention: bool = True  # 群组需 @提及
    group_policy: QQGroupPolicy = Field(default_factory=QQGroupPolicy)  # 群组策略
    show_reasoning: bool = True  # 默认显示思考过程
    working_directory: str | None = None  # 渠道 agent 运行目录（缺省 = 默认工作区）


class ChannelsConfig(BaseModel):
    """所有渠道配置容器（channels.json）

    顶层属性为渠道名，未来新增渠道在此平级追加字段。

    Attributes:
        feishu: 飞书渠道配置
        weixin: 微信渠道配置
    """

    feishu: FeishuChannelConfig = Field(default_factory=FeishuChannelConfig)  # 飞书配置
    weixin: WeixinChannelConfig = Field(default_factory=WeixinChannelConfig)  # 微信配置
    qq: QQChannelConfig = Field(default_factory=QQChannelConfig)  # QQ 配置

    def has_enabled_channels(self) -> bool:
        """是否有任何已启用的渠道

        遍历 ChannelRegistry 检查每个渠道的 enabled 字段。

        Returns:
            bool: 任一渠道 enabled 为 True 时返回 True
        """
        from illusion_forge.channels.registry import ChannelRegistry

        for desc in ChannelRegistry.all_descriptors():
            channel_cfg = getattr(self, desc.config_attr, None)
            if channel_cfg is not None and channel_cfg.enabled:
                return True
        return False

    def enabled_channel_names(self) -> list[str]:
        """返回所有已启用渠道的名称列表

        遍历 ChannelRegistry 收集已启用渠道名。

        Returns:
            list[str]: 已启用渠道名列表
        """
        from illusion_forge.channels.registry import ChannelRegistry

        names: list[str] = []
        for desc in ChannelRegistry.all_descriptors():
            channel_cfg = getattr(self, desc.config_attr, None)
            if channel_cfg is not None and channel_cfg.enabled:
                names.append(desc.name)
        return names


def load_channels_config(config_path: Path | None = None) -> ChannelsConfig:
    """从 channels.json 加载渠道配置

    文件不存在或损坏时返回空配置（无渠道），记日志，不抛异常。

    Args:
        config_path: 配置文件路径。None 时使用默认位置 ~/.illusion/channels.json

    Returns:
        ChannelsConfig: 渠道配置
    """
    if config_path is None:
        from illusion_forge.config.paths import get_channels_file_path
        config_path = get_channels_file_path()

    if not config_path.exists():
        return ChannelsConfig()

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        return ChannelsConfig.model_validate(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("渠道配置文件损坏，使用空配置: %s", exc)
        return ChannelsConfig()


def save_channels_config(config: ChannelsConfig, config_path: Path | None = None) -> None:
    """将渠道配置持久化到 channels.json

    Args:
        config: 要保存的配置
        config_path: 写入路径。None 时使用默认位置
    """
    if config_path is None:
        from illusion_forge.config.paths import get_channels_file_path
        config_path = get_channels_file_path()

    config_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        config_path,
        config.model_dump_json(indent=2) + "\n",
    )
