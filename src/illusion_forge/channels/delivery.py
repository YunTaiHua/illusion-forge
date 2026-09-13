"""渠道投递模块

提供独立的渠道消息投递功能，供 cron scheduler 等进程外场景使用。
构造临时 API 客户端发送消息后关闭，不需要运行中的 Channel 实例。
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
from typing import TYPE_CHECKING

from illusion_forge.channels.feishu.adapter import _feishu_executor  # 飞书 SDK 专用线程池

if TYPE_CHECKING:
    from illusion_forge.channels.config import (
        ChannelsConfig,
        FeishuChannelConfig,
        QQChannelConfig,
        WeixinChannelConfig,
    )

logger = logging.getLogger(__name__)


def parse_deliver_targets(
    deliver_to_list: list[str],
    chat_id: str = "",
) -> list[tuple[str, str, str]]:
    """解析 deliver_to 列表为 [(channel_name, target_chat_id, chat_type), ...]

    支持多目标投递：每个目标独立解析，跳过无效项。

    格式：
        - 'channel:chat_id' → (channel, chat_id, "")
        - 仅渠道名 + chat_id 有值 → (channel, chat_id, "")

    返回三段元组以兼容多渠道接口签名，chat_type 为空串表示按渠道默认策略
    （QQ 渠道在 _deliver_qq 中走"先群组失败回退 C2C"容错路径）。

    Args:
        deliver_to_list: 投递目标列表
        chat_id: 来源会话 ID（仅渠道名时回退使用）

    Returns:
        list[tuple[str, str, str]]: 解析成功的 (channel, chat_id, chat_type) 列表
            chat_type 始终为 ""（由 _deliver_qq 内部决定路由策略）
            空列表 = 不投递或全部解析失败
    """
    targets: list[tuple[str, str, str]] = []
    for item in deliver_to_list:
        if not isinstance(item, str) or not item:
            continue

        if ":" in item:
            channel, cid = item.split(":", 1)
            channel = channel.strip()
            cid = cid.strip()
            if channel and cid:
                targets.append((channel, cid, ""))
            else:
                logger.warning("deliver_to 项格式无效: %s", item)
            continue

        # 仅渠道名：用来源会话 chat_id（从渠道会话创建的任务）
        channel = item.strip()
        if not channel:
            continue
        if chat_id:
            targets.append((channel, chat_id, ""))
        else:
            logger.info(
                "deliver_to=%s 缺少 chat_id，跳过该项",
                item,
            )
    return targets


async def deliver_to_channel(
    channel_name: str,
    chat_id: str,
    text: str,
    *,
    config: ChannelsConfig | None = None,
    markdown: bool | None = None,
    chat_type: str = "",
) -> bool:
    """投递文本消息到指定渠道会话

    复用各渠道 adapter 的 markdown 渲染和分片逻辑，确保跨渠道文本投递
    与渠道内 send_text 行为一致。

    Args:
        channel_name: 渠道名（"feishu"/"qq"/"weixin"）
        chat_id: 目标会话 ID
        text: 文本内容（可能包含 markdown 标记）
        config: 渠道配置（None 时从 channels.json 加载）
        markdown: 是否按 markdown 渲染
            None=按渠道配置自动判断（feishu=True, qq=config.markdown_support, weixin=False）
            True/False=显式覆盖
        chat_type: QQ 投递目标类型，"group"=群组, "c2c"=私聊, ""=未知
            仅 QQ 需要显式指定（其他渠道通过 chat_id 前缀自动判断）
            空串时 QQ 走"先群组失败回退 C2C"容错策略

    Returns:
        bool: 是否投递成功
    """
    if config is None:
        from illusion_forge.channels.config import load_channels_config
        config = load_channels_config()

    if channel_name == "feishu":
        return await _deliver_feishu(config.feishu, chat_id, text, markdown=markdown)
    if channel_name == "qq":
        return await _deliver_qq(config.qq, chat_id, text, markdown=markdown, chat_type=chat_type)
    if channel_name == "weixin":
        return await _deliver_weixin(config.weixin, chat_id, text, markdown=markdown)

    logger.warning("未知渠道: %s", channel_name)
    return False


async def _deliver_feishu(
    config: FeishuChannelConfig,
    chat_id: str,
    text: str,
    *,
    markdown: bool | None = None,
) -> bool:
    """飞书文本投递：复用 send_card 走 markdown 交互卡片

    飞书默认支持 markdown，markdown=True/None 时走 send_card 卡片渲染，
    markdown=False 时降级为纯文本 msg_type=text。
    卡片承载超长内容，无分片需求。
    """
    if not config.enabled:
        logger.warning("飞书渠道未启用，跳过投递")
        return False
    try:
        from illusion_forge.channels.feishu.messaging import build_lark_client, send_card

        client = build_lark_client(config)
        # markdown=None 或 True → 走卡片（飞书默认支持 markdown）
        # markdown=False → 走纯文本
        use_markdown = markdown is not False
        if use_markdown:
            # send_card 内部用 msg_type=interactive + markdown 元素，飞书客户端渲染
            await send_card(client, chat_id, text)
        else:
            import json

            from illusion_forge.channels.feishu.messaging import resolve_receive_id
            try:
                from lark_oapi.api.im.v1 import CreateMessageRequest
            except ImportError:
                logger.error("飞书投递需要 lark_oapi")
                return False

            _receive_id, receive_id_type = resolve_receive_id(chat_id)
            body = {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            }
            builder = CreateMessageRequest.builder().receive_id_type(receive_id_type)
            builder = builder.request_body(body)  # pyright: ignore[reportArgumentType]
            req = builder.build()
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(_feishu_executor, client.im.v1.message.create, req)
            if not resp.success():
                logger.error("飞书纯文本投递失败: code=%s msg=%s", resp.code, resp.msg)
                return False
        return True
    except Exception:
        logger.exception("飞书投递异常")
        return False


async def _deliver_qq(
    config: QQChannelConfig,
    chat_id: str,
    text: str,
    *,
    markdown: bool | None = None,
    chat_type: str = "",
) -> bool:
    """QQ 文本投递：复用 split_text 分片 + send_c2c/group_message

    QQ Bot API v2 需要 msg_id（被动消息引用）才能可靠投递主动消息，
    cron/跨渠道投递场景无 msg_id，群聊主动消息可能受限。

    Args:
        chat_type: "group"=群组, "c2c"=私聊, ""=未知
            空串时走"先群组失败回退 C2C"容错策略
            显式指定可避免回退消耗（如 chat_id 实为 group_openid 时 C2C 必然失败）
    """
    if not config.enabled:
        logger.warning("QQ 渠道未启用，跳过投递")
        return False
    try:
        import aiohttp

        from illusion_forge.channels.qq.api import (
            ensure_token,
            send_c2c_message,
            send_group_message,
            split_text,
        )

        # markdown=None → 按渠道配置；否则用显式值
        use_markdown = config.markdown_support if markdown is None else markdown

        logger.info(
            "QQ 投递开始: chat_id=%s chat_type=%s markdown=%s chunks=%d",
            chat_id, chat_type or "auto(group→c2c)", use_markdown,
            len(split_text(text)) if text else 0,
        )

        async with aiohttp.ClientSession() as session:
            token = await ensure_token(
                session, config.app_id, config.client_secret,
            )

            # 分片投递：QQ split_text 代码块感知，max_length=4000
            chunks = split_text(text) if text else [text]
            if not chunks:
                chunks = [text] if text else []

            async def _send_chunk(*, is_group: bool, chunk: str) -> None:
                """发送单个分片，markdown 失败时降级为纯文本重试

                QQ Bot API v2 markdown
                消息需预批准模板，普通开发者账号会触发 err_code=11255。
                """
                md = use_markdown
                target_label = "群组" if is_group else "C2C"
                for attempt in range(3):
                    try:
                        if is_group:
                            await send_group_message(
                                session, token, chat_id, chunk, msg_id="",
                                markdown=md,
                            )
                        else:
                            await send_c2c_message(
                                session, token, chat_id, chunk, msg_id="",
                                markdown=md,
                            )
                        logger.info(
                            "QQ %s投递成功 (attempt %d): markdown=%s chunk_len=%d",
                            target_label, attempt + 1, md, len(chunk),
                        )
                        return
                    except Exception as exc:
                        if md and attempt == 0:
                            # markdown 权限/格式错误，自动降级为纯文本
                            logger.info(
                                "QQ %smarkdown 发送失败，自动降级为纯文本重试: %s",
                                target_label, exc,
                            )
                            md = False
                            continue
                        if attempt < 2:
                            logger.info(
                                "QQ %s投递失败 (attempt %d/3)，重试中: %s",
                                target_label, attempt + 1, exc,
                            )
                            await asyncio.sleep(2)
                        else:
                            raise

            async def _send_to_target(*, is_group: bool) -> None:
                """向指定类型目标发送所有分片"""
                for i, chunk in enumerate(chunks):
                    if i > 0:
                        await asyncio.sleep(1.5)  # 分片间隔，防限流
                    await _send_chunk(is_group=is_group, chunk=chunk)

            # 路由策略
            if chat_type == "group":
                await _send_to_target(is_group=True)
            elif chat_type == "c2c":
                await _send_to_target(is_group=False)
            else:
                # chat_type 未知：先群组失败回退 C2C（QQ C2C/group openid 格式相同）
                try:
                    await _send_to_target(is_group=True)
                except (TimeoutError, aiohttp.ClientError, RuntimeError, ValueError, OSError) as group_exc:
                    logger.info(
                        "QQ 群组投递失败，自动降级为 C2C (chat_id=%s): %s",
                        chat_id, group_exc,
                    )
                    await _send_to_target(is_group=False)
        return True
    except Exception:
        logger.exception("QQ 投递异常")
        return False


async def _deliver_weixin(
    config: WeixinChannelConfig,
    chat_id: str,
    text: str,
    *,
    markdown: bool | None = None,
) -> bool:
    """微信文本投递：复用 send_message + _split_text 分片

    微信 iLink API 不支持 markdown，markdown 参数被忽略。
    复用 _split_text 按段落边界分片（max_len=2000）。
    context_token 从持久化文件加载（iLink 硬约束：每 peer 回复必须回传）。

    errcode 处理：
        - SESSION_EXPIRED: 去掉 context_token 降级重试一次
        - RATE_LIMIT: 等待后重试
        - 其他非零 errcode: 重试最多 3 次
    """
    # 微信不支持 markdown，显式 True 也降级为纯文本
    del markdown  # 忽略参数

    if not config.enabled:
        logger.warning("微信渠道未启用，跳过投递")
        return False
    try:
        import uuid

        from illusion_forge.channels.weixin.ilink_api import (
            RATE_LIMIT_ERRCODE,
            SESSION_EXPIRED_ERRCODE,
            _make_ssl_connector,
            _split_text,
            send_message,
        )

        connector = _make_ssl_connector()
        import aiohttp
        async with aiohttp.ClientSession(trust_env=True, connector=connector) as session:
            # 尝试从持久化文件加载 context_token
            context_token = _load_weixin_context_token(chat_id)
            if not context_token:
                logger.error(
                    "微信文本投递缺少 context_token (chat_id=%s)，"
                    "iLink API 会静默不投递。"
                    "context_token 会在 24 小时后过期，请让用户重新发送一条消息给机器人以建立会话。",
                    chat_id,
                )
                return False
            logger.info(
                "微信投递开始: chat_id=%s text_len=%d has_ctx=True",
                chat_id, len(text),
            )

            # 分片投递：微信 _split_text 段落边界，max_len=2000
            chunks = _split_text(text) if text else []
            if not chunks:
                chunks = [text] if text else []

            sent_any = False
            for chunk in chunks:
                ctx_token = context_token
                # 重试逻辑（最多 3 次）
                for attempt in range(3):
                    resp = await send_message(
                        session,
                        base_url=config.base_url,
                        token=config.token,
                        to=chat_id,
                        text=chunk,
                        context_token=ctx_token or None,
                        client_id=f"cron-{uuid.uuid4().hex[:16]}",
                    )
                    errcode = resp.get("errcode", 0)
                    if errcode == SESSION_EXPIRED_ERRCODE:
                        # 会话过期：去掉 context_token 降级重试一次
                        if attempt == 0:
                            ctx_token = ""
                            logger.warning("微信会话过期，去掉 context_token 重试")
                            continue
                        logger.warning(
                            "微信投递失败: 会话过期 (chat_id=%s errcode=%d)",
                            chat_id, errcode,
                        )
                        return False
                    if errcode == RATE_LIMIT_ERRCODE:
                        logger.warning("微信投递限流，3s 后重试")
                        await asyncio.sleep(3)
                        continue
                    if errcode != 0:
                        logger.warning(
                            "微信投递失败 (attempt %d/3): errcode=%d resp=%s",
                            attempt + 1, errcode, str(resp)[:200],
                        )
                        if attempt < 2:
                            await asyncio.sleep(1)
                            continue
                        return False
                    # errcode == 0：成功
                    logger.info(
                        "微信分片投递成功 (attempt %d): chunk_len=%d",
                        attempt + 1, len(chunk),
                    )
                    sent_any = True
                    break
                else:
                    # for-else: 重试 3 次都失败
                    return False

                # 分片间隔，防限流
                await asyncio.sleep(1.5)
            return sent_any
    except Exception:
        logger.exception("微信投递异常")
        return False


def _load_weixin_context_token(user_id: str) -> str:
    """从微信 context_token 持久化文件加载指定用户的 token

    微信 iLink API 硬约束：每 peer 回复必须回传 context_token。
    daemon 运行时会持久化到 channels_data/weixin/context_tokens.json，
    cron 子进程读取该文件获取 context_token。

    Args:
        user_id: 微信用户 ID

    Returns:
        str: context_token，未找到返回空串
    """
    try:
        import json

        from illusion_forge.config.paths import get_channels_data_dir

        token_path = get_channels_data_dir() / "weixin" / "context_tokens.json"
        if not token_path.exists():
            return ""
        data = json.loads(token_path.read_text(encoding="utf-8"))
        return str(data.get(user_id, ""))
    except (ImportError, OSError, ValueError, KeyError, AttributeError) as exc:
        logger.warning("加载微信 context_token 失败 (user=%s): %s", user_id, exc)
        return ""


async def deliver_file_to_channel(
    channel_name: str,
    chat_id: str,
    file_path: str,
    *,
    config: ChannelsConfig | None = None,
    caption: str = "",
) -> bool:
    """投递本地文件到指定渠道会话

    读取 channels.json 构造临时 API 客户端，发送文件/图片后关闭。
    供 SendToChannelTool 跨渠道文件传输调用。

    Args:
        channel_name: 目标渠道名（"feishu"/"qq"/"weixin"）
        chat_id: 目标会话 ID
        file_path: 本地文件路径
        config: 渠道配置（None 时从 channels.json 加载）
        caption: 可选附注文字

    Returns:
        bool: 是否投递成功
    """
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        logger.error("文件不存在: %s", file_path)
        return False

    if config is None:
        from illusion_forge.channels.config import load_channels_config
        config = load_channels_config()

    if channel_name == "feishu":
        return await _deliver_file_feishu(config.feishu, chat_id, file_path, caption)
    if channel_name == "qq":
        return await _deliver_file_qq(config.qq, chat_id, file_path, caption)
    if channel_name == "weixin":
        return await _deliver_file_weixin(config.weixin, chat_id, file_path, caption)

    logger.warning("未知渠道: %s", channel_name)
    return False


async def _deliver_file_feishu(
    config: FeishuChannelConfig, chat_id: str, file_path: str, caption: str,
) -> bool:
    """飞书文件投递：复用 feishu.messaging.send_file

    send_file 内部按扩展名路由 file_type（pdf/doc/xls/ppt/opus/mp4/stream），
    避免硬编码 "stream" 导致部分文件类型发送失败。
    """
    if not config.enabled:
        logger.warning("飞书渠道未启用，跳过文件投递")
        return False
    try:
        from illusion_forge.channels.feishu.messaging import build_lark_client, send_file

        client = build_lark_client(config)
        await send_file(client, config, chat_id, file_path, caption=caption)
        return True
    except Exception:
        logger.exception("飞书文件投递异常")
        return False


async def _deliver_file_qq(
    config: QQChannelConfig, chat_id: str, file_path: str, caption: str,
) -> bool:
    """QQ 文件投递：upload_file + send_media_message

    QQ Bot API v2 文件上传流程：
        1. upload_file: 分片上传（upload_prepare → PUT parts → complete），获取 file_info
        2. send_media_message: 发送富媒体消息（msg_type=7），引用 file_info

    投递目标类型由 chat_id 隐式决定：先尝试群组（is_group=True），
    失败回退 C2C（is_group=False）。注意：群组主动消息可能受限（无 msg_id）。

    如果有 caption，先发一条文本消息，再发文件。
    """
    if not config.enabled:
        logger.warning("QQ 渠道未启用，跳过文件投递")
        return False
    try:
        import aiohttp

        from illusion_forge.channels.qq.api import (
            MEDIA_TYPE_FILE,
            MEDIA_TYPE_IMAGE,
            ensure_token,
            send_c2c_message,
            send_group_message,
            send_media_message,
            upload_file,
        )

        async with aiohttp.ClientSession() as session:
            token = await ensure_token(
                session, config.app_id, config.client_secret,
            )

            async def _send_with_caption(*, is_group: bool) -> None:
                """先发 caption 文本（如有），再上传文件并发送富媒体消息"""
                if caption:
                    if is_group:
                        await send_group_message(
                            session, token, chat_id, caption, msg_id="",
                            markdown=config.markdown_support,
                        )
                    else:
                        await send_c2c_message(
                            session, token, chat_id, caption, msg_id="",
                            markdown=config.markdown_support,
                        )
                # 根据 MIME 类型选择正确的 file_type（图片用 IMAGE，其他用 FILE）
                content_type, _ = mimetypes.guess_type(file_path)
                file_type = MEDIA_TYPE_IMAGE if (content_type and content_type.startswith("image/")) else MEDIA_TYPE_FILE
                # 上传文件
                file_info_data = await upload_file(
                    session, token, chat_id, file_path,
                    is_group=is_group, file_type=file_type,
                )
                file_info = str(file_info_data.get("file_info", ""))
                if not file_info:
                    raise RuntimeError("upload_file 未返回 file_info")
                # 发送富媒体消息
                await send_media_message(
                    session, token, chat_id, file_info,
                    is_group=is_group, msg_id="",
                )

            # 先尝试群组（更常见的 cron 场景）
            try:
                await _send_with_caption(is_group=True)
                return True
            except (TimeoutError, aiohttp.ClientError, RuntimeError, ValueError, OSError) as group_exc:
                logger.warning(
                    "QQ 群组文件投递失败 (chat_id=%s)，best-effort 尝试 C2C"
                    "（若 chat_id 为 group_openid 则 C2C 也会失败）: %s",
                    chat_id, group_exc,
                )
            # 回退 C2C
            await _send_with_caption(is_group=False)
        return True
    except Exception:
        logger.exception("QQ 文件投递异常")
        return False


async def _deliver_file_weixin(
    config: WeixinChannelConfig, chat_id: str, file_path: str, caption: str,
) -> bool:
    """微信文件投递：AES-128-ECB 加密 → 上传 CDN → 发送含媒体 item 的消息

    直接复用 weixin adapter._send_file 的实现思路：
        1. 读取文件明文 → 生成随机 16 字节 AES 密钥 → AES-128-ECB + PKCS#7 加密
        2. get_upload_url 获取 CDN 上传 URL
        3. upload_ciphertext 上传密文到 CDN，拿到 encrypted_query_param
        4. 按 MIME 选择 ITEM_IMAGE（image/*）或 ITEM_FILE
        5. caption 先发一条文本消息（用 send_message）
        6. _api_post 发送含 media item 的消息
    """
    if not config.enabled:
        logger.warning("微信渠道未启用，跳过文件投递")
        return False
    try:
        import base64
        import hashlib
        import mimetypes
        import secrets
        import uuid
        from pathlib import Path

        import aiohttp

        from illusion_forge.channels.weixin.ilink_api import (
            EP_SEND_MESSAGE,
            ITEM_FILE,
            ITEM_IMAGE,
            MEDIA_FILE,
            MEDIA_IMAGE,
            MSG_STATE_FINISH,
            MSG_TYPE_BOT,
            _aes128_ecb_encrypt,
            _aes_padded_size,
            _api_post,
            _cdn_upload_url,
            _make_ssl_connector,
            get_upload_url,
            send_message,
            upload_ciphertext,
        )

        path = Path(file_path)
        # 文件可能很大（图片/视频/文档），用 to_thread 避免阻塞事件循环
        plaintext = await asyncio.to_thread(path.read_bytes)
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        # 按 MIME 选择媒体类型和 item 构造器
        if mime.startswith("image/"):
            media_type = MEDIA_IMAGE
            item_type = ITEM_IMAGE
        else:
            media_type = MEDIA_FILE
            item_type = ITEM_FILE

        filekey = secrets.token_hex(16)
        aes_key = secrets.token_bytes(16)
        rawsize = len(plaintext)
        rawfilemd5 = hashlib.md5(plaintext).hexdigest()
        ciphertext = _aes128_ecb_encrypt(plaintext, aes_key)

        connector = _make_ssl_connector()
        async with aiohttp.ClientSession(trust_env=True, connector=connector) as session:
            context_token = _load_weixin_context_token(chat_id)
            if not context_token:
                logger.error(
                    "微信文件投递缺少 context_token (chat_id=%s)，"
                    "iLink API 会静默不投递。"
                    "context_token 会在 24 小时后过期，请让用户重新发送一条消息给机器人以建立会话。",
                    chat_id,
                )
                return False
            logger.info(
                "微信文件投递: chat_id=%s has_context_token=True",
                chat_id,
            )

            # 获取上传 URL
            upload_response = await get_upload_url(
                session,
                base_url=config.base_url, token=config.token,
                to_user_id=chat_id, media_type=media_type, filekey=filekey,
                rawsize=rawsize, rawfilemd5=rawfilemd5,
                filesize=_aes_padded_size(rawsize), aeskey_hex=aes_key.hex(),
            )
            upload_param = str(upload_response.get("upload_param") or "")
            upload_full_url = str(upload_response.get("upload_full_url") or "")

            if upload_full_url:
                upload_url = upload_full_url
            elif upload_param:
                upload_url = _cdn_upload_url(config.cdn_base_url, upload_param, filekey)
            else:
                logger.error(
                    "微信 getuploadurl 返回既无 upload_param 也无 upload_full_url: %s",
                    upload_response,
                )
                return False

            # 上传密文到 CDN
            encrypted_query_param = await upload_ciphertext(
                session, ciphertext=ciphertext, upload_url=upload_url,
            )

            # iLink API 期望 aes_key 为 base64(hex_string)，而非 base64(raw_bytes)
            # 否则接收端解密失败，图片显示为灰框
            aes_key_for_api = base64.b64encode(
                aes_key.hex().encode("ascii"),
            ).decode("ascii")

            # 构造 media item
            media = {
                "encrypt_query_param": encrypted_query_param,
                "aes_key": aes_key_for_api,
                "encrypt_type": 1,
            }
            if item_type == ITEM_IMAGE:
                media_item: dict[str, object] = {
                    "type": ITEM_IMAGE,
                    "image_item": {
                        "media": media,
                        "mid_size": len(ciphertext),
                    },
                }
            else:
                media_item = {
                    "type": ITEM_FILE,
                    "file_item": {
                        "media": media,
                        "file_name": path.name,
                        "len": str(rawsize),
                    },
                }

            # 先发 caption 文本
            if caption:
                caption_client_id = f"illusion-cron-{uuid.uuid4().hex[:16]}"
                await send_message(
                    session, base_url=config.base_url, token=config.token,
                    to=chat_id, text=caption, context_token=context_token or None,
                    client_id=caption_client_id,
                )

            # 发送含媒体 item 的消息
            media_client_id = f"illusion-cron-{uuid.uuid4().hex[:16]}"
            message_payload: dict[str, object] = {
                "from_user_id": "",
                "to_user_id": chat_id,
                "client_id": media_client_id,
                "message_type": MSG_TYPE_BOT,
                "message_state": MSG_STATE_FINISH,
                "item_list": [media_item],
            }
            if context_token:
                message_payload["context_token"] = context_token

            resp = await _api_post(
                session,
                base_url=config.base_url, endpoint=EP_SEND_MESSAGE,
                payload={"msg": message_payload}, token=config.token,
                timeout_ms=15000,
            )
            errcode = resp.get("errcode", 0)
            if errcode != 0:
                logger.error("微信文件投递失败: errcode=%s resp=%s", errcode, resp)
                return False
        return True
    except Exception:
        logger.exception("微信文件投递异常")
        return False
