"""渠道抽象基类
================

定义所有消息渠道（飞书、未来的 telegram 等）的统一接口。

类说明：
    - InboundMessage: 标准化的入站消息
    - Channel: 渠道抽象基类

设计原则：精简接口，只保留飞书渠道当前需要的能力。
未来新增渠道若有额外需求，再扩展基类。
"""
from __future__ import annotations

from abc import ABC, abstractmethod  # 抽象基类支持
from collections.abc import AsyncIterator  # 类型注解
from dataclasses import dataclass, field  # 数据类
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from illusion_forge.config.settings import Settings  # 仅类型检查时导入，避免循环


@dataclass(frozen=True)
class Attachment:
    """入站消息附件

    所有渠道的附件（图片/文件/视频/音频）归一化为此结构。

    Attributes:
        id: 附件标识（在消息内唯一，如 "1", "2"）
        media_type: 媒体类型，"image" | "file" | "video" | "audio"
        filename: 原始文件名
        size: 字节数（未知为 0）
        file_key: 渠道特定文件标识（飞书 image_key/file_key、QQ file_info）
        download_url: 下载 URL（部分渠道提供）
        message_id: 所属消息 ID（用于附件下载时查找渠道特定的会话凭证，
                     如微信 AES 密钥缓存）
    """

    id: str
    media_type: str  # "image" | "file" | "video" | "audio"
    filename: str
    size: int = 0
    file_key: str = ""
    download_url: str = ""
    message_id: str = ""


@dataclass
class SessionInfo:
    """渠道活跃会话摘要（供跨渠道提示词展示）

    由各 SessionStore.list_active 返回，用于在系统提示词中列出
    其他渠道的活跃会话，帮助 LLM 决定跨渠道文件投递目标。

    Attributes:
        chat_id: 渠道内会话标识（如飞书 ou_xxx/oc_xxx，微信 wxid_xxx，QQ openid_xxx）
        user_name: 用户显示名（如有，否则空串）
        chat_type: 会话类型 "dm" / "group"
        last_active: 最后活跃时间 ISO 字符串（如 "2026-06-28 10:30"）
    """
    chat_id: str
    user_name: str = ""
    chat_type: str = ""
    last_active: str = ""


@dataclass(frozen=True)
class InboundMessage:
    """标准化入站消息

    所有渠道的原始事件归一化为此结构后，再交给 ChannelRunner 处理。

    Attributes:
        text: 消息文本内容
        chat_id: 会话标识（飞书 DM 用 open_id，群组用 chat_id）
        chat_type: 会话类型，dm（私聊）或 group（群聊）
        user_id: 发送者标识（飞书 open_id）
        user_name: 发送者显示名
        message_id: 入站消息 ID，用于回复定位
        is_bot: 发送者是否为机器人
        thread_id: 话题/线程 ID（可选）
    """

    text: str  # 消息文本
    chat_id: str  # 会话标识
    chat_type: str  # "dm" | "group"
    user_id: str  # 发送者 ID
    user_name: str  # 发送者名
    message_id: str  # 消息 ID
    is_bot: bool = False  # 是否机器人
    thread_id: str = ""  # 线程 ID
    attachments: list[Attachment] = field(default_factory=list)  # 附件列表


class Channel(ABC):
    """消息渠道抽象基类

    子类需实现连接、监听、收发、关闭等核心方法。

    Attributes:
        name: 渠道名称（如 "feishu"）
    """

    name: str  # 子类设置

    def __init__(self, config: Any, settings: Settings) -> None:
        """初始化渠道

        Args:
            config: 渠道特定配置（如 FeishuChannelConfig）
            settings: IllusionForge 主设置（用于获取模型、API key 等）
        """
        self.config = config  # 渠道配置
        self.settings = settings  # 主设置

    @abstractmethod
    async def connect(self) -> None:
        """建立渠道连接（如 WS 长连接）"""
        ...

    @abstractmethod
    def listen(self) -> AsyncIterator[InboundMessage]:
        """返回入站消息的异步迭代器

        实现应为 async generator，不断 yield InboundMessage。
        """
        ...

    @abstractmethod
    async def send_text(self, chat_id: str, text: str, *, reply_to: str = "") -> str:
        """发送文本消息，返回新消息 ID

        Args:
            chat_id: 目标会话
            text: 文本内容（纯文本或 markdown）
            reply_to: 要回复的消息 ID（可选）

        Returns:
            str: 新发送的消息 ID
        """
        ...

    @abstractmethod
    async def edit_message(self, chat_id: str, message_id: str, text: str) -> None:
        """编辑已发送消息的文本（用于流式编辑）

        Args:
            chat_id: 会话标识
            message_id: 要编辑的消息 ID
            text: 新文本内容
        """
        ...

    async def send_file(self, chat_id: str, file_path: str, *, reply_to: str = "") -> None:
        """发送文件（deprecated，按扩展名路由到 send_image/send_document）

        Args:
            chat_id: 目标会话
            file_path: 本地文件路径
            reply_to: 引用的消息 ID（部分渠道需要，如 QQ 群聊被动消息）
        """
        from pathlib import Path

        ext = Path(file_path).suffix.lower()
        if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
            await self.send_image(chat_id, file_path, reply_to=reply_to)
        else:
            await self.send_document(chat_id, file_path, reply_to=reply_to)

    async def send_image(
        self, chat_id: str, image_path: str, *, caption: str = "", reply_to: str = ""
    ) -> str:
        """发送图片到指定会话，返回新消息 ID

        Args:
            chat_id: 目标会话
            image_path: 本地图片文件路径
            caption: 可选附注文字
            reply_to: 引用的消息 ID（部分渠道需要，如 QQ 群聊被动消息）

        Returns:
            str: 新消息 ID

        Raises:
            NotImplementedError: 渠道不支持图片发送
        """
        raise NotImplementedError(f"{self.name} does not support send_image")

    async def send_document(
        self, chat_id: str, file_path: str, *, caption: str = "", reply_to: str = ""
    ) -> str:
        """发送文件（非图片）到指定会话，返回新消息 ID

        Args:
            chat_id: 目标会话
            file_path: 本地文件路径
            caption: 可选附注文字
            reply_to: 引用的消息 ID（部分渠道需要，如 QQ 群聊被动消息）

        Returns:
            str: 新消息 ID

        Raises:
            NotImplementedError: 渠道不支持文件发送
        """
        raise NotImplementedError(f"{self.name} does not support send_document")

    async def download_attachment(
        self, attachment: Attachment, save_path: str
    ) -> str:
        """下载入站附件到本地路径

        Args:
            attachment: 附件对象（来自 InboundMessage.attachments）
            save_path: 本地保存路径

        Returns:
            str: 实际保存路径

        Raises:
            NotImplementedError: 渠道不支持附件下载
        """
        raise NotImplementedError(f"{self.name} does not support download_attachment")

    @abstractmethod
    async def shutdown(self) -> None:
        """关闭渠道连接，释放资源"""
        ...

    async def start_typing(self, chat_id: str) -> None:
        """开始打字状态指示（可选，微信渠道实现）

        飞书不需要打字状态（用卡片流式更新），默认空操作。
        微信渠道重写此方法发送 iLink 打字状态。

        Args:
            chat_id: 目标会话
        """
        # 默认空操作

    async def stop_typing(self, chat_id: str) -> None:
        """停止打字状态指示（可选，微信渠道实现）

        Args:
            chat_id: 目标会话
        """
        # 默认空操作

    def get_bot_id(self) -> str:
        """返回 bot 自身标识（用于自回显检测）

        子类应在 connect() 后返回 bot 的 user_id / open_id。
        默认返回空串，表示未获取到。

        Returns:
            str: bot 自身标识
        """
        return ""

    async def health_probe(self) -> bool:
        """健康探活（默认返回 True，子类可覆盖）

        用于事件超时看门狗判定渠道是否僵死。
        飞书：调用 bot_info API 检测网络和认证；微信/QQ：已有重连机制，默认 True。

        Returns:
            bool: 渠道健康返回 True，僵死返回 False
        """
        return True
