"""渠道注册表
============

每个渠道注册一个 ChannelDescriptor，包含元数据和工厂函数。

模块加载时自动注册三个内置渠道（feishu/weixin/qq）。
注册表只记录元数据，不导入渠道 SDK——依赖检查在 serve.py 实际启动时进行。

类说明：
    - ChannelDescriptor: 单个渠道的元数据描述符
    - ChannelRegistry: 渠道注册表，集中管理所有渠道的元数据

使用示例：
    >>> from illusion_forge.channels.registry import ChannelRegistry
    >>> desc = ChannelRegistry.get("feishu")
    >>> if desc and cfg.feishu.enabled:
    ...     print(f"渠道 {desc.name} 已启用")
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass
class ChannelDescriptor:
    """单个渠道的元数据描述符

    用于消除散落在各处的硬编码分支，每个渠道注册一份元数据。

    Attributes:
        name: 渠道名（"feishu" / "weixin" / "qq"）
        config_attr: ChannelsConfig 上的属性名（如 "feishu"）
        config_class: 渠道配置类（如 FeishuChannelConfig）
        adapter_class: 渠道适配器类（如 FeishuChannel）
        dependencies: 依赖的 Python 包名元组（如 ("lark_oapi",)）
        session_store_factory: 根据 channel + data_dir + group_sessions_per_user 构造 session_store
        command_handler_factory: 根据 channel + session_store 构造 command_handler
        fingerprint_factory: 根据渠道配置生成指纹标识字符串（用于检测配置变更）
        start_msg_key: 启动文案的 i18n key（如 "channel_starting"）
        start_msg_needs_channel_name: 启动文案是否需要传入 {channel} 参数（feishu 用）
    """

    name: str  # 渠道名
    config_attr: str  # ChannelsConfig 上的属性名
    config_class: type  # 渠道配置类
    adapter_class: type  # 渠道适配器类
    dependencies: tuple[str, ...]  # 依赖的 Python 包名
    session_store_factory: Callable[..., Any]  # 会话存储工厂
    command_handler_factory: Callable[[Any, Any], Any]  # 命令处理器工厂
    fingerprint_factory: Callable[[Any], str]  # 配置指纹工厂
    start_msg_key: str = "channel_starting"  # 启动文案 i18n key
    start_msg_needs_channel_name: bool = False  # 启动文案是否需要 {channel} 参数


class ChannelRegistry:
    """渠道注册表，集中管理所有渠道的元数据

    使用类变量 _channels 存储所有已注册的渠道描述符。
    模块加载时自动注册三个内置渠道。

    测试隔离：测试中如需注册 mock 渠道，请用 snapshot() 保存原状态，
    测试结束后用 restore() 恢复，避免污染其他测试。
    """

    _channels: ClassVar[dict[str, ChannelDescriptor]] = {}

    @classmethod
    def register(cls, descriptor: ChannelDescriptor) -> None:
        """注册一个渠道描述符

        Args:
            descriptor: 渠道描述符
        """
        cls._channels[descriptor.name] = descriptor

    @classmethod
    def all_descriptors(cls) -> list[ChannelDescriptor]:
        """返回所有已注册的渠道描述符列表

        Returns:
            list[ChannelDescriptor]: 所有渠道描述符
        """
        return list(cls._channels.values())

    @classmethod
    def get(cls, name: str) -> ChannelDescriptor | None:
        """按名称查询渠道描述符

        Args:
            name: 渠道名

        Returns:
            ChannelDescriptor | None: 找到返回描述符，未找到返回 None
        """
        return cls._channels.get(name)

    @classmethod
    def snapshot(cls) -> dict[str, ChannelDescriptor]:
        """返回当前注册表的快照（浅拷贝）

        用于测试隔离：测试注册 mock 渠道前先快照，测试后用 restore() 恢复。

        Returns:
            dict[str, ChannelDescriptor]: 当前注册表的浅拷贝
        """
        return dict(cls._channels)

    @classmethod
    def restore(cls, snapshot: dict[str, ChannelDescriptor]) -> None:
        """从快照恢复注册表

        用于测试隔离：将注册表恢复到 snapshot() 时的状态。

        Args:
            snapshot: snapshot() 返回的快照
        """
        cls._channels = dict(snapshot)


# === 工厂函数：延迟导入渠道实现，避免顶层依赖 SDK ===


def _feishu_session_store_factory(
    channel: Any, data_dir: Any, group_sessions_per_user: bool
) -> Any:
    """飞书会话存储工厂"""
    from illusion_forge.channels.feishu.session_map import FeishuSessionStore

    return FeishuSessionStore(
        data_dir=data_dir,
        group_sessions_per_user=group_sessions_per_user,
    )


def _feishu_command_handler_factory(channel: Any, session_store: Any) -> Any:
    """飞书命令处理器工厂"""
    from illusion_forge.channels.feishu.commands import FeishuCommandHandler

    return FeishuCommandHandler(channel, session_store)


def _feishu_fingerprint_factory(cfg: Any) -> str:
    """飞书配置指纹"""
    return f"feishu:{cfg.app_id}"


def _weixin_session_store_factory(
    channel: Any, data_dir: Any, group_sessions_per_user: bool
) -> Any:
    """微信会话存储工厂（微信只私聊，不使用 group_sessions_per_user）"""
    from illusion_forge.channels.weixin.session_map import WeixinSessionStore

    return WeixinSessionStore(data_dir=data_dir)


def _weixin_command_handler_factory(channel: Any, session_store: Any) -> Any:
    """微信命令处理器工厂"""
    from illusion_forge.channels.weixin.commands import WeixinCommandHandler

    return WeixinCommandHandler(channel, session_store)


def _weixin_fingerprint_factory(cfg: Any) -> str:
    """微信配置指纹"""
    return f"weixin:{cfg.account_id}:{cfg.token}"


def _qq_session_store_factory(
    channel: Any, data_dir: Any, group_sessions_per_user: bool
) -> Any:
    """QQ 会话存储工厂"""
    from illusion_forge.channels.qq.session_map import QQSessionStore

    return QQSessionStore(
        data_dir=data_dir,
        group_sessions_per_user=group_sessions_per_user,
    )


def _qq_command_handler_factory(channel: Any, session_store: Any) -> Any:
    """QQ 命令处理器工厂"""
    from illusion_forge.channels.qq.commands import QQCommandHandler

    return QQCommandHandler(channel, session_store)


def _qq_fingerprint_factory(cfg: Any) -> str:
    """QQ 配置指纹"""
    return f"qq:{cfg.app_id}:{cfg.client_secret}"


# === 模块加载时注册三个内置渠道 ===
# 延迟导入配置类和适配器类（它们不依赖 SDK，可安全导入）
from illusion_forge.channels.config import (
    FeishuChannelConfig,
    QQChannelConfig,
    WeixinChannelConfig,
)
from illusion_forge.channels.feishu.adapter import FeishuChannel
from illusion_forge.channels.qq.adapter import QQChannel
from illusion_forge.channels.weixin.adapter import WeixinChannel

ChannelRegistry.register(
    ChannelDescriptor(
        name="feishu",
        config_attr="feishu",
        config_class=FeishuChannelConfig,
        adapter_class=FeishuChannel,
        dependencies=("lark_oapi",),
        session_store_factory=_feishu_session_store_factory,
        command_handler_factory=_feishu_command_handler_factory,
        fingerprint_factory=_feishu_fingerprint_factory,
        start_msg_key="channel_starting",
        start_msg_needs_channel_name=True,  # feishu 启动文案带 {channel} 参数
    )
)
ChannelRegistry.register(
    ChannelDescriptor(
        name="weixin",
        config_attr="weixin",
        config_class=WeixinChannelConfig,
        adapter_class=WeixinChannel,
        dependencies=("aiohttp", "cryptography", "qrcode"),
        session_store_factory=_weixin_session_store_factory,
        command_handler_factory=_weixin_command_handler_factory,
        fingerprint_factory=_weixin_fingerprint_factory,
        start_msg_key="channel_starting_weixin",
    )
)
ChannelRegistry.register(
    ChannelDescriptor(
        name="qq",
        config_attr="qq",
        config_class=QQChannelConfig,
        adapter_class=QQChannel,
        dependencies=("aiohttp",),
        session_store_factory=_qq_session_store_factory,
        command_handler_factory=_qq_command_handler_factory,
        fingerprint_factory=_qq_fingerprint_factory,
        start_msg_key="channel_starting_qq",
    )
)
