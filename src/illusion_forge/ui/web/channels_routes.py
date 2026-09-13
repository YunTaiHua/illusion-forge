"""Web 端渠道配置 REST 路由模块
================================

供 web 前端通过 HTTP 管理 channels.json（飞书 / 微信 / QQ 渠道配置）
以及控制渠道守护进程内各渠道 runner 的运行时启停。

与 env_routes.py 职责分离：本模块只处理渠道配置的读取、更新与运行控制。

路由清单：
    - GET  /api/channels                        读取当前全部渠道配置
    - PATCH /api/channels                       部分更新渠道配置（仅合并请求中提供的渠道字段）
    - GET  /api/channels/status                 查询各渠道运行时状态（守护进程内 runner 活跃情况）
    - POST /api/channels/{name}/start           启动指定渠道 runner（通过 IPC 通知守护进程）
    - POST /api/channels/{name}/stop            停止指定渠道 runner（通过 IPC 通知守护进程）
    - POST /api/channels/{name}/test            测试渠道连接（飞书/QQ 校验凭据，微信走扫码流程）
    - POST /api/channels/weixin/qr/start        获取微信登录二维码（不开浏览器，返回二维码内容供前端渲染）
    - GET  /api/channels/weixin/qr/status       轮询微信扫码状态（wait/scaned/confirmed/expired 等）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from illusion_forge.channels.config import (
    ChannelsConfig,
    load_channels_config,
    save_channels_config,
)

logger = logging.getLogger(__name__)


class UpdateChannelsRequest(BaseModel):
    """渠道配置部分更新请求体。

    仅提供需要更新的渠道配置字典，未提供的渠道保持不变。
    每个渠道的字典会与现有配置浅合并（顶层字段覆盖）。

    Attributes:
        feishu: 飞书渠道配置增量（可选）
        weixin: 微信渠道配置增量（可选）
        qq: QQ 渠道配置增量（可选）
    """

    feishu: dict[str, Any] | None = None
    weixin: dict[str, Any] | None = None
    qq: dict[str, Any] | None = None


class StartChannelRequest(BaseModel):
    """启动渠道请求体。

    Attributes:
        working_directory: 渠道 agent 运行目录（可选；提供时先写入渠道
            配置再启动，守护进程按该目录锚定 agent 运行。缺省沿用现有
            渠道配置或默认工作区）
    """

    working_directory: str | None = None


class TestConnectionRequest(BaseModel):
    """测试连接请求体（携带待校验的凭据，不依赖已保存的配置）

    Attributes:
        app_id: 飞书/QQ 应用 ID
        app_secret: 飞书应用密钥
        client_secret: QQ 应用密钥
        domain: 飞书域名（feishu/lark），默认 feishu
    """

    app_id: str = ""
    app_secret: str = ""
    client_secret: str = ""
    domain: str = "feishu"


def register_channels_routes(app: FastAPI, host_config: Any | None = None) -> None:
    """注册渠道配置 HTTP 路由到 FastAPI app。

    Args:
        app: FastAPI 应用实例
        host_config: 宿主配置（保留参数以与 env_routes 签名对齐，当前未使用）
    """

    @app.get("/api/channels")
    async def get_channels() -> dict[str, Any]:
        """读取当前渠道配置。

        Returns:
            dict: 全部渠道配置（feishu/weixin/qq），结构与 ChannelsConfig 一致
        """
        cfg = load_channels_config()
        return cfg.model_dump()

    @app.patch("/api/channels")
    async def update_channels(req: UpdateChannelsRequest) -> dict[str, Any]:
        """部分更新渠道配置并持久化。

        仅合并请求中提供的渠道字段（顶层浅合并），其余渠道保持不变。
        合并后经 ChannelsConfig 校验，校验失败返回 400。

        多目录空间：启用渠道（enabled=true）必须配置运行目录
        （working_directory），否则渠道 agent 无法锚定工作区。

        Returns:
            dict: 更新后的全部渠道配置
        """
        cfg = load_channels_config()
        data = cfg.model_dump()
        # 对每个提供的渠道做顶层浅合并，未提供的渠道保持原值
        if req.feishu is not None:
            data["feishu"] = {**data["feishu"], **req.feishu}
        if req.weixin is not None:
            data["weixin"] = {**data["weixin"], **req.weixin}
        if req.qq is not None:
            data["qq"] = {**data["qq"], **req.qq}
        try:
            new_cfg = ChannelsConfig.model_validate(data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # 启用校验：渠道 enabled 时必须有 working_directory
        for ch_name in ("feishu", "weixin", "qq"):
            ch_cfg = getattr(new_cfg, ch_name, None)
            if ch_cfg is not None and ch_cfg.enabled and not ch_cfg.working_directory:
                raise HTTPException(
                    status_code=400,
                    detail=f"启用 {ch_name} 渠道必须指定运行目录（working_directory）",
                )
        save_channels_config(new_cfg)
        return new_cfg.model_dump()

    @app.get("/api/channels/status")
    async def get_channels_status() -> dict[str, Any]:
        """查询各渠道运行时状态（守护进程内 runner 活跃情况）

        直接在 FastAPI 事件循环中创建 DaemonClient 并 async ping 守护进程，
        从 pong 响应的 channels 字段提取运行状态。
        守护进程未运行时返回空字典。

        Note:
            不使用 channels.get_channels_runtime_status() 的同步封装，
            避免其内部 _run_coro_sync 在已有事件循环时创建新线程运行协程，
            导致 Windows Named Pipe 跨线程句柄问题。

        Returns:
            dict: {渠道名: {healthy: bool, running: bool}}
        """
        return await _async_query_channels_status()

    @app.post("/api/channels/{name}/start")
    async def start_channel(name: str, req: StartChannelRequest | None = None) -> dict[str, Any]:
        """启动指定渠道 runner（通过 IPC 通知守护进程）

        直接在 FastAPI 事件循环中创建 DaemonClient 并 async 发送 start_channel。
        若守护进程未运行，先通过 asyncio.to_thread 调用 maybe_spawn_channel_daemon
        拉起（避免阻塞事件循环），spawn 后短暂等待再重试连接。

        多目录空间：请求体可携带 working_directory，启动前先写入渠道配置
        （未注册目录自动注册到工作区列表），渠道 agent 固定在该目录运行，
        不再隐式继承守护进程启动目录。

        实际 runner 创建在守护进程事件循环中异步进行，前端可通过
        GET /api/channels/status 轮询确认运行状态。

        Args:
            name: 渠道名（feishu/weixin/qq）
            req: 启动请求体（working_directory 可选）

        Returns:
            dict: {"ok": bool, "daemon_running": bool}
        """
        # 先落盘渠道运行目录（在 spawn/notify 之前，确保守护进程读到新配置）
        req = req or StartChannelRequest()
        raw_dir = (req.working_directory or "").strip()
        if raw_dir:
            resolved_dir, err = await asyncio.to_thread(_resolve_channel_dir, raw_dir)
            if resolved_dir is None:
                raise HTTPException(status_code=400, detail=err or "目录路径非法")
            cfg = load_channels_config()
            channel_cfg = getattr(cfg, name, None)
            if channel_cfg is None:
                raise HTTPException(status_code=404, detail=f"Unknown channel: {name}")
            channel_cfg.working_directory = resolved_dir
            save_channels_config(cfg)

        # 第一次尝试：直接连接发送 start_channel
        ok = await _async_notify_channel(name, "start")
        if ok:
            return {"ok": True, "daemon_running": True}

        # 失败时先判断守护进程是否存活（区分"未运行"和"运行但返回 error"）
        if await _async_daemon_alive():
            # 守护进程在运行但 start_channel 返回 error（如配置缺失）
            return {"ok": False, "daemon_running": True}

        # 守护进程未运行，尝试拉起
        from illusion_forge.channels import maybe_spawn_channel_daemon

        await asyncio.to_thread(maybe_spawn_channel_daemon, spawn_if_missing=True)
        # spawn 后重置持久连接（旧连接可能已失效）
        await _reset_persistent_client()
        # 守护进程刚 spawn，等待其 IPC server 就绪后重试
        for _ in range(10):  # 最多等 5s
            await asyncio.sleep(0.5)
            ok = await _async_notify_channel(name, "start")
            if ok:
                return {"ok": True, "daemon_running": True}
        return {"ok": False, "daemon_running": False}

    @app.post("/api/channels/{name}/stop")
    async def stop_channel(name: str) -> dict[str, Any]:
        """停止指定渠道 runner（通过 IPC 通知守护进程）

        直接在 FastAPI 事件循环中创建 DaemonClient 并 async 发送 stop_channel。
        通知守护进程设置 stop_event、取消 task、关闭 runner。
        守护进程未运行时视为已停止，返回 ok=True。

        Args:
            name: 渠道名（feishu/weixin/qq）

        Returns:
            dict: {"ok": bool}
        """
        ok = await _async_notify_channel(name, "stop")
        if ok:
            return {"ok": True}
        # 通知失败：若守护进程未运行，渠道必然已停止，视为成功
        if not await _async_daemon_alive():
            return {"ok": True}
        return {"ok": False}

    @app.post("/api/channels/{name}/test")
    async def test_channel_connection(name: str, req: TestConnectionRequest) -> dict[str, Any]:
        """测试渠道连接（校验凭据是否有效，不启动 runner）

        飞书：调用 tenant_access_token/internal 接口，返回 token 则成功。
        QQ：调用 getAppAccessToken 接口，返回 token 则成功。
        微信：走扫码流程，不支持 test，返回 400 提示用 qr/start。

        Args:
            name: 渠道名（feishu/qq）
            req: 待校验的凭据

        Returns:
            dict: {"ok": bool, "message": str}
        """
        if name == "feishu":
            return await _test_feishu(req.app_id, req.app_secret, req.domain)
        elif name == "qq":
            return await _test_qq(req.app_id, req.client_secret)
        elif name == "weixin":
            # 微信走扫码流程，不支持 test connection
            raise HTTPException(
                status_code=400,
                detail="weixin requires QR scan login, use /api/channels/weixin/qr/start instead",
            )
        else:
            raise HTTPException(status_code=404, detail=f"unknown channel: {name}")

    @app.post("/api/channels/weixin/qr/start")
    async def weixin_qr_start() -> dict[str, Any]:
        """获取微信登录二维码（不开浏览器）

        调用 iLink Bot API 获取二维码，返回 qrcode（hex token，用于轮询状态）
        和 qr_content（URL 或 hex，供前端用 qrcode 库渲染为图片供手机扫描）。
        同时用后端 qrcode 库生成 PNG 图片的 base64 编码，前端可直接用
        <img src="data:image/png;base64,..."> 显示，无需前端 QR 依赖。

        Returns:
            dict: {"qrcode": str, "qr_content": str, "qr_image_b64": str}
            失败时返回 500。
        """
        import base64
        import io

        import aiohttp

        from illusion_forge.channels.weixin.ilink_api import (
            ILINK_BASE_URL,
            QR_TIMEOUT_MS,
            _make_ssl_connector,
            get_bot_qrcode,
        )

        timeout = aiohttp.ClientTimeout(total=QR_TIMEOUT_MS / 1000)
        connector = _make_ssl_connector()
        async with aiohttp.ClientSession(
            timeout=timeout, trust_env=True, connector=connector,
        ) as session:
            try:
                qr_resp = await get_bot_qrcode(session, base_url=ILINK_BASE_URL)
            except (TimeoutError, OSError, RuntimeError, ValueError) as exc:
                logger.warning("获取微信二维码失败: %s", exc)
                raise HTTPException(status_code=500, detail=str(exc))
        qrcode_hex = qr_resp.get("qrcode", "")
        qr_url = qr_resp.get("qrcode_img_content", "")
        if not qrcode_hex:
            raise HTTPException(status_code=500, detail="qrcode is empty")
        # 优先用 URL（微信才能识别为登录链接），否则用 hex
        qr_content = qr_url or qrcode_hex
        # 生成 QR PNG base64（qrcode 库延迟导入，扫码阶段可能未装）
        qr_image_b64 = ""
        try:
            import qrcode

            img = qrcode.make(qr_content)
            buf = io.BytesIO()
            img.save(buf, format="PNG")  # type: ignore[call-arg]
            qr_image_b64 = base64.b64encode(buf.getvalue()).decode()
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            logger.warning("生成二维码图片失败: %s", exc)
        return {"qrcode": qrcode_hex, "qr_content": qr_content, "qr_image_b64": qr_image_b64}

    @app.get("/api/channels/weixin/qr/status")
    async def weixin_qr_status(
        qrcode: str = Query(..., description="二维码 hex token"),
        base_url: str = Query("", description="API 入口（扫码重定向后可能改变）"),
    ) -> dict[str, Any]:
        """轮询微信扫码状态

        调用 iLink Bot API 查询扫码状态。状态包括：
        - wait: 等待扫码
        - scaned: 已扫码，等待确认
        - scaned_but_redirect: 已扫码但需重定向（返回新 base_url）
        - confirmed: 已确认，返回凭据并自动保存到 channels.json
        - expired: 二维码过期

        Args:
            qrcode: 二维码 hex token
            base_url: API 入口（空则用默认 ILINK_BASE_URL）

        Returns:
            dict: {"status": str, ...}，confirmed 时含 credentials 并保存到配置
        """
        import aiohttp

        from illusion_forge.channels.weixin.ilink_api import (
            ILINK_BASE_URL,
            QR_TIMEOUT_MS,
            _make_ssl_connector,
            get_qrcode_status,
        )

        api_base = base_url or ILINK_BASE_URL
        timeout = aiohttp.ClientTimeout(total=QR_TIMEOUT_MS / 1000)
        connector = _make_ssl_connector()
        async with aiohttp.ClientSession(
            timeout=timeout, trust_env=True, connector=connector,
        ) as session:
            try:
                status_resp = await get_qrcode_status(
                    session, base_url=api_base, qrcode=qrcode,
                )
            except (TimeoutError, OSError, RuntimeError, ValueError) as exc:
                logger.warning("查询微信扫码状态失败: %s", exc)
                raise HTTPException(status_code=500, detail=str(exc))

        status = str(status_resp.get("status") or "wait")
        result: dict[str, Any] = {"status": status}

        # scaned_but_redirect：返回新 base_url 供前端下次轮询使用
        if status == "scaned_but_redirect":
            redirect_host = str(status_resp.get("redirect_host") or "")
            if redirect_host:
                result["base_url"] = f"https://{redirect_host}"

        # confirmed：提取凭据并保存到 channels.json
        elif status == "confirmed":
            account_id = str(status_resp.get("ilink_bot_id") or "")
            token = str(status_resp.get("bot_token") or "")
            confirmed_base_url = str(status_resp.get("baseurl") or api_base)
            user_id = str(status_resp.get("ilink_user_id") or "")
            if not account_id or not token:
                raise HTTPException(status_code=500, detail="confirmed but credentials incomplete")
            # 保存凭据到 channels.json
            try:
                cfg = load_channels_config()
                cfg.weixin.account_id = account_id
                cfg.weixin.token = token
                cfg.weixin.base_url = confirmed_base_url
                cfg.weixin.user_id = user_id
                save_channels_config(cfg)
            except (OSError, ValueError, RuntimeError) as exc:
                logger.warning("保存微信凭据失败: %s", exc)
                raise HTTPException(status_code=500, detail=f"save credentials failed: {exc}")
            result["credentials"] = {
                "account_id": account_id,
                "token": token,
                "base_url": confirmed_base_url,
                "user_id": user_id,
            }

        return result


def _resolve_channel_dir(raw: str) -> tuple[str | None, str | None]:
    """校验并注册渠道运行目录（复用已注册工作区或自动注册新目录）。

    与工作目录设置相同的校验规则（expanduser、缺失目录自动创建）；
    目录合法但未注册时自动加入工作区注册表（web 端列表立即可见）。

    Returns:
        tuple[str | None, str | None]: (规范化目录或 None, 错误信息或 None)
    """
    from illusion_forge.cli.workspace import validate_and_normalize
    from illusion_forge.services import workspace_registry

    resolved, err = validate_and_normalize(raw)
    if resolved is None:
        return None, err or "目录路径非法"
    path = str(resolved)
    if not workspace_registry.is_known_workspace(path):
        entry, reg_err = workspace_registry.register_workspace(path)
        if entry is None:
            return None, reg_err or "注册目录失败"
    return workspace_registry.normalize_workspace_path(path), None


async def _test_feishu(app_id: str, app_secret: str, domain: str) -> dict[str, Any]:
    """测试飞书连接：调用 tenant_access_token/internal 接口校验凭据

    Args:
        app_id: 飞书应用 App ID
        app_secret: 飞书应用 App Secret
        domain: 域名（feishu/lark）

    Returns:
        dict: {"ok": bool, "message": str}
    """
    import json as _json
    import urllib.request as _urllib

    if not app_id or not app_secret:
        return {"ok": False, "message": "app_id and app_secret are required"}
    base = "https://open.feishu.cn" if domain == "feishu" else "https://open.larksuite.com"
    url = f"{base}/open-apis/auth/v3/tenant_access_token/internal"
    payload = _json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = _urllib.Request(url, data=payload, headers={"Content-Type": "application/json"})

    # 在线程中执行阻塞的 HTTP 请求，避免阻塞事件循环
    def _do_request() -> dict[str, Any]:
        with _urllib.urlopen(req, timeout=10) as resp:
            return cast(dict[str, Any], _json.loads(resp.read()))

    try:
        data = await asyncio.to_thread(_do_request)
    except (OSError, _json.JSONDecodeError) as exc:
        return {"ok": False, "message": f"request failed: {exc}"}
    if data.get("tenant_access_token"):
        return {"ok": True, "message": "success"}
    return {"ok": False, "message": str(data.get("msg") or "invalid credentials")}


async def _test_qq(app_id: str, client_secret: str) -> dict[str, Any]:
    """测试 QQ 连接：调用 getAppAccessToken 接口校验凭据

    Args:
        app_id: QQ 应用 App ID
        client_secret: QQ 应用 App Secret

    Returns:
        dict: {"ok": bool, "message": str}
    """
    import json as _json
    import urllib.request as _urllib

    if not app_id or not client_secret:
        return {"ok": False, "message": "app_id and client_secret are required"}
    url = "https://bots.qq.com/app/getAppAccessToken"
    payload = _json.dumps({"appId": app_id, "clientSecret": client_secret}).encode()
    req = _urllib.Request(url, data=payload, headers={"Content-Type": "application/json"})

    # 在线程中执行阻塞的 HTTP 请求，避免阻塞事件循环
    def _do_request() -> dict[str, Any]:
        with _urllib.urlopen(req, timeout=10) as resp:
            return cast(dict[str, Any], _json.loads(resp.read()))

    try:
        data = await asyncio.to_thread(_do_request)
    except (OSError, _json.JSONDecodeError) as exc:
        return {"ok": False, "message": f"request failed: {exc}"}
    if data.get("access_token"):
        return {"ok": True, "message": "success"}
    return {"ok": False, "message": str(data.get("message") or "invalid credentials")}


# ─── async IPC 辅助函数（持久连接版） ───
# 使用模块级持久 DaemonClient 复用连接，避免频繁创建/关闭临时连接。
# 临时连接关闭后守护进程连接计数可能归零（若 Web 后端的 ref 连接未就绪），
# 触发 wait_for_no_connections → 守护进程自动退出。
# 持久连接保持活跃，连接计数始终 >= 1，守护进程不会误退出。

_persistent_client: Any = None
_persistent_client_lock = asyncio.Lock()


async def _get_persistent_client() -> Any:
    """获取或创建持久 IPC 客户端（复用连接，不关闭）

    连接失败时返回 None。连接断开时自动重置以便下次重连。
    使用 asyncio.Lock 串行化创建分支，避免并发请求同时创建多个 client。

    Returns:
        DaemonClient 实例或 None（守护进程未运行）
    """
    global _persistent_client
    # 快速路径：连接有效时直接返回（不加锁）
    if _persistent_client is not None and _persistent_client.is_connected:
        return _persistent_client
    # 慢速路径：加锁创建/重连
    async with _persistent_client_lock:
        # double-check（可能在等锁期间已被其他请求创建）
        if _persistent_client is not None and _persistent_client.is_connected:
            return _persistent_client
        import os

        from illusion_forge.daemon_ipc import DaemonClient, DaemonType

        # 关闭旧连接（可能已断开）
        if _persistent_client is not None:
            try:
                await _persistent_client.close()
            except (OSError, RuntimeError):
                pass
            _persistent_client = None
        # 创建新连接
        client = DaemonClient(daemon_type=DaemonType.CHANNEL, pid=os.getpid())
        try:
            connected = await client.connect()
        except (OSError, RuntimeError, ConnectionError):
            return None
        if not connected:
            return None
        _persistent_client = client
        return client


async def _reset_persistent_client() -> None:
    """重置持久连接（操作失败时调用，下次自动重连）"""
    global _persistent_client
    if _persistent_client is not None:
        try:
            await _persistent_client.close()
        except (OSError, RuntimeError):
            pass
        _persistent_client = None


async def _async_query_channels_status() -> dict[str, dict[str, bool]]:
    """通过持久连接查询渠道运行状态

    从 pong 响应的 channels 字段提取运行状态。
    守护进程未运行时返回空字典。

    Returns:
        dict: {渠道名: {healthy: bool, running: bool}}
    """
    client = await _get_persistent_client()
    if client is None:
        return {}
    try:
        pong = await client.ping(timeout=2.0)
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as exc:
        logger.debug("查询渠道状态失败: %s", exc)
        await _reset_persistent_client()
        return {}
    if pong is None:
        return {}
    channels = pong.get("channels")
    if not isinstance(channels, dict):
        return {}
    # 规范化：确保每条目含 healthy/running 布尔字段
    result: dict[str, dict[str, bool]] = {}
    for ch_name, info in channels.items():
        if not isinstance(info, dict):
            continue
        result[str(ch_name)] = {
            "healthy": bool(info.get("healthy", False)),
            "running": bool(info.get("running", False)),
        }
    return result


async def _async_notify_channel(name: str, action: str) -> bool:
    """通过持久连接通知守护进程启动/停止指定渠道

    Args:
        name: 渠道名（feishu/weixin/qq）
        action: "start" 或 "stop"

    Returns:
        bool: 通知成功返回 True，守护进程未运行或通知失败返回 False
    """
    client = await _get_persistent_client()
    if client is None:
        return False
    try:
        if action == "start":
            resp = await client.start_channel(name, timeout=5.0)
        else:
            resp = await client.stop_channel(name, timeout=5.0)
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as exc:
        logger.debug("通知渠道 %s %s 失败: %s", name, action, exc)
        await _reset_persistent_client()
        return False
    if resp is None:
        await _reset_persistent_client()
        return False
    return bool(resp.get("type") == "ok")


async def _async_daemon_alive() -> bool:
    """检查渠道守护进程是否存活（通过持久连接 ping）

    Returns:
        bool: 守护进程在运行返回 True
    """
    client = await _get_persistent_client()
    if client is None:
        return False
    try:
        pong = await client.ping(timeout=2.0)
    except (OSError, RuntimeError, ConnectionError, TimeoutError):
        await _reset_persistent_client()
        return False
    return pong is not None
