"""渠道媒体收发工具

提供 LLM 可调用的文件/图片收发工具。工具为每会话构造，
内部持有渠道实例和当前 chat_id。

工具说明：
    - SendMediaTool: 发送本地文件到当前渠道会话
    - ReceiveMediaTool: 下载收到的附件到本地路径

设计原则：LLM 只负责文件传输，不需要读取文件内容。
例如 SolidWorks 建模文件，LLM 无法读取，但可以传输。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
from pydantic import BaseModel, Field

from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult

if TYPE_CHECKING:
    from illusion_forge.channels.base import Attachment, Channel


# 媒体类型扩展名映射
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"}


def _route_media_type(file_path: str) -> str:
    """根据扩展名路由媒体类型

    Args:
        file_path: 文件路径

    Returns:
        str: "image" | "video" | "audio" | "file"
    """
    ext = Path(file_path).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    return "file"


class SendMediaInput(BaseModel):
    """发送媒体工具输入

    Attributes:
        file_path: 本地文件路径
        caption: 可选附注文字
    """

    file_path: str = Field(..., description="Local file path to send")
    caption: str = Field("", description="Optional caption text")


class SendMediaTool(BaseTool[SendMediaInput]):
    """发送本地文件到当前渠道会话

    文件按扩展名自动路由：图片 (.jpg/.png/.webp/.gif) 作为原生图片发送，
    其他文件作为可下载文档发送。LLM 不需要读取文件内容——这是本地机器
    与渠道之间的文件传输。

    不支持的渠道会返回错误。
    """

    name = "send_media"
    description = (
        "Send a local file (image/document/video/audio) to the current channel chat. "
        "Files are routed by extension: images as native photos, others as documents. "
        "Use this for file transfer — you don't need to read the file content."
    )
    input_model = SendMediaInput

    def __init__(
        self, channel: Channel, chat_id: str, *, message_id: str = ""
    ) -> None:
        """初始化

        Args:
            channel: 渠道实例
            chat_id: 当前会话 ID
            message_id: 当前入站消息 ID（作为 reply_to 传给渠道，
                部分渠道如 QQ 群聊需要此 ID 才能发送被动消息）
        """
        self._channel = channel
        self._chat_id = chat_id
        self._message_id = message_id

    async def execute(
        self, arguments: BaseModel, context: ToolExecutionContext
    ) -> ToolResult:
        """执行媒体发送"""
        assert isinstance(arguments, SendMediaInput)
        path = Path(arguments.file_path)
        if not path.exists():
            return ToolResult(
                output=f"File not found: {arguments.file_path}", is_error=True
            )

        media_type = _route_media_type(arguments.file_path)
        try:
            if media_type == "image":
                msg_id = await self._channel.send_image(
                    self._chat_id, arguments.file_path,
                    caption=arguments.caption, reply_to=self._message_id,
                )
            else:
                msg_id = await self._channel.send_document(
                    self._chat_id, arguments.file_path,
                    caption=arguments.caption, reply_to=self._message_id,
                )
            return ToolResult(
                output=f"Sent {media_type}: {path.name} (message_id={msg_id})"
            )
        except NotImplementedError as exc:
            return ToolResult(output=str(exc), is_error=True)
        except (
            aiohttp.ClientError, OSError, RuntimeError, ValueError,
            AttributeError, TypeError, TimeoutError,
        ) as exc:
            # 底层 upload_ciphertext/get_upload_url 已含重试；此处仍失败
            # 说明重试用尽，提示 LLM 可再次尝试 send_media
            return ToolResult(
                output=f"Failed to send media after retries: {exc}. "
                       "You may retry send_media.",
                is_error=True,
            )


class ReceiveMediaInput(BaseModel):
    """接收媒体工具输入

    Attributes:
        attachment_id: 附件 ID（来自消息上下文中的附件列表）
        save_path: 本地保存路径
    """

    attachment_id: str = Field(
        ..., description="Attachment ID from the received message context"
    )
    save_path: str = Field(..., description="Local path to save the attachment")


class ReceiveMediaTool(BaseTool[ReceiveMediaInput]):
    """下载收到的附件到本地路径

    当用户通过渠道发送文件/图片时，附件信息会出现在消息上下文中。
    调用此工具以下载附件到指定本地路径。LLM 不需要读取下载的文件——
    这是渠道与本地机器之间的文件传输。
    """

    name = "receive_media"
    description = (
        "Download a received media attachment to a local path. "
        "When a user sends a file/image, attachment info appears in the message context "
        "as '[收到附件 <id>: <filename> (<type>, <size>)]'. "
        "Call this with the attachment_id (the number from the bracket) and save_path "
        "to download the file. Use this for file transfer — you don't need to read the file content."
    )
    input_model = ReceiveMediaInput

    def __init__(
        self, channel: Channel, chat_id: str, attachments: list[Attachment]
    ) -> None:
        """初始化

        Args:
            channel: 渠道实例
            chat_id: 当前会话 ID
            attachments: 当前消息的附件列表
        """
        self._channel = channel
        self._chat_id = chat_id
        self._attachments = {a.id: a for a in attachments}

    async def execute(
        self, arguments: BaseModel, context: ToolExecutionContext
    ) -> ToolResult:
        """执行附件下载"""
        assert isinstance(arguments, ReceiveMediaInput)
        attachment = self._attachments.get(arguments.attachment_id)
        if attachment is None:
            available = ", ".join(self._attachments.keys()) or "(none)"
            return ToolResult(
                output=f"Attachment not found: id={arguments.attachment_id}. "
                f"Available: {available}",
                is_error=True,
            )

        try:
            save_path = Path(arguments.save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            actual_path = await self._channel.download_attachment(
                attachment, arguments.save_path
            )
            return ToolResult(
                output=f"Downloaded: {attachment.filename} → {actual_path}"
            )
        except NotImplementedError as exc:
            return ToolResult(output=str(exc), is_error=True)
        except (
            aiohttp.ClientError, OSError, RuntimeError, ValueError,
            AttributeError, TypeError, TimeoutError,
        ) as exc:
            return ToolResult(
                output=f"Failed to download attachment: {exc}", is_error=True
            )
