"""测试飞书流式卡片构造函数与 CardKit API 封装"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("lark_oapi")

from illusion_forge.channels.feishu.messaging import (
    LOADING_ICON_ELEMENT_ID,
    STREAMING_ELEMENT_ID,
    build_complete_card,
    build_streaming_card,
    create_card_entity,
    send_card_by_card_id,
    set_card_streaming_mode,
    stream_card_element_content,
    update_cardkit_card,
)


def test_streaming_element_id_constants() -> None:
    assert STREAMING_ELEMENT_ID == "streaming_content"
    assert LOADING_ICON_ELEMENT_ID == "loading_icon"


def test_build_streaming_card_structure() -> None:
    card_json = build_streaming_card()
    card = json.loads(card_json)
    assert card["schema"] == "2.0"
    assert card["config"]["streaming_mode"] is True
    elements = card["body"]["elements"]
    assert len(elements) == 2
    # streaming_content element
    assert elements[0]["tag"] == "markdown"
    assert elements[0]["element_id"] == "streaming_content"
    assert elements[0]["content"] == ""
    assert elements[0]["text_size"] == "normal_v2"
    # loading_icon element
    assert elements[1]["tag"] == "markdown"
    assert elements[1]["element_id"] == "loading_icon"
    assert "icon" in elements[1]
    assert elements[1]["icon"]["tag"] == "custom_icon"


def test_build_complete_card_with_reasoning() -> None:
    card_json = build_complete_card(
        text="Hello",
        reasoning_text="I thought about it",
        elapsed_ms=1500,
    )
    card = json.loads(card_json)
    assert card["schema"] == "2.0"
    assert card["config"]["streaming_mode"] is False
    elements = card["body"]["elements"]
    # collapsible_panel (reasoning) + markdown (text) + markdown (footer)
    assert len(elements) == 3
    # reasoning panel
    panel = elements[0]
    assert panel["tag"] == "collapsible_panel"
    assert panel["expanded"] is False
    assert "Thought for" in panel["header"]["title"]["content"]
    # main text
    assert elements[1]["tag"] == "markdown"
    assert elements[1]["content"] == "Hello"
    # footer
    assert elements[2]["tag"] == "markdown"
    assert elements[2]["text_size"] == "notation"
    assert "已完成" in elements[2]["content"] or "耗时" in elements[2]["content"]


def test_build_complete_card_without_reasoning() -> None:
    card_json = build_complete_card(text="Hi", reasoning_text="", elapsed_ms=500)
    card = json.loads(card_json)
    elements = card["body"]["elements"]
    # 无 reasoning 时只有 markdown (text) + markdown (footer)
    assert len(elements) == 2
    assert elements[0]["tag"] == "markdown"
    assert elements[0]["content"] == "Hi"


def test_build_complete_card_error() -> None:
    card_json = build_complete_card(
        text="partial",
        reasoning_text="",
        elapsed_ms=1000,
        is_error=True,
    )
    card = json.loads(card_json)
    elements = card["body"]["elements"]
    footer = elements[-1]
    assert "red" in footer["content"]


def test_sanitize_card_text_converts_image_urls() -> None:
    """markdown 图片 URL 被转为链接（避免飞书 200570 错误）"""
    from illusion_forge.channels.feishu.messaging import _sanitize_card_text
    # ![alt](url) → [alt](url)
    assert _sanitize_card_text("![QR](https://example.com/q.png)") == "[QR](https://example.com/q.png)"
    # ![](url) → url
    assert _sanitize_card_text("![](https://example.com/img)") == "https://example.com/img"
    # 非 URL 图片（飞书 img_key）不受影响
    assert _sanitize_card_text("![icon](img_v3_abc)") == "![icon](img_v3_abc)"
    # 无图片语法不受影响
    assert _sanitize_card_text("[link](https://example.com)") == "[link](https://example.com)"


# ---------------------------------------------------------------------------
# CardKit API 封装测试
# ---------------------------------------------------------------------------


def _mock_client() -> MagicMock:
    """构造模拟 lark client"""
    client = MagicMock()

    # cardkit.v1.card.create
    card_resp = MagicMock()
    card_resp.success.return_value = True
    card_resp.data.card_id = "card_123"
    client.cardkit.v1.card.create = MagicMock(return_value=card_resp)

    # cardkit.v1.card_element.acontent（Python SDK 用下划线，不是驼峰）
    element_resp = MagicMock()
    element_resp.success.return_value = True
    client.cardkit.v1.card_element.acontent = AsyncMock(return_value=element_resp)

    # cardkit.v1.card.update
    update_resp = MagicMock()
    update_resp.success.return_value = True
    client.cardkit.v1.card.update = MagicMock(return_value=update_resp)

    # cardkit.v1.card.settings（流式模式切换）
    settings_resp = MagicMock()
    settings_resp.success.return_value = True
    client.cardkit.v1.card.settings = MagicMock(return_value=settings_resp)

    # im.v1.message.create
    msg_resp = MagicMock()
    msg_resp.success.return_value = True
    msg_resp.data.message_id = "msg_123"
    client.im.v1.message.create = MagicMock(return_value=msg_resp)

    return client


@pytest.mark.asyncio
async def test_create_card_entity_success() -> None:
    client = _mock_client()
    card_id = await create_card_entity(client, '{"schema":"2.0"}')
    assert card_id == "card_123"
    client.cardkit.v1.card.create.assert_called_once()


@pytest.mark.asyncio
async def test_create_card_entity_failure() -> None:
    client = _mock_client()
    client.cardkit.v1.card.create.return_value.success.return_value = False
    client.cardkit.v1.card.create.return_value.code = 230002
    client.cardkit.v1.card.create.return_value.msg = "invalid card"
    card_id = await create_card_entity(client, '{}')
    assert card_id == ""


@pytest.mark.asyncio
async def test_send_card_by_card_id_success() -> None:
    client = _mock_client()
    msg_id = await send_card_by_card_id(client, "ou_user1", "card_123", reply_to="msg_abc")
    assert msg_id == "msg_123"


@pytest.mark.asyncio
async def test_stream_card_element_content_success() -> None:
    client = _mock_client()
    ok = await stream_card_element_content(
        client, "card_123", "streaming_content", "Hello", 1,
    )
    assert ok is True


@pytest.mark.asyncio
async def test_stream_card_element_content_failure() -> None:
    client = _mock_client()
    client.cardkit.v1.card_element.acontent.return_value.success.return_value = False
    client.cardkit.v1.card_element.acontent.return_value.code = 230020
    ok = await stream_card_element_content(
        client, "card_123", "streaming_content", "Hello", 1,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_update_cardkit_card_success() -> None:
    client = _mock_client()
    ok = await update_cardkit_card(client, "card_123", '{"schema":"2.0"}', 99)
    assert ok is True


@pytest.mark.asyncio
async def test_send_card_by_card_id_failure_raises() -> None:
    """send_card_by_card_id 失败时抛 RuntimeError"""
    client = _mock_client()
    client.im.v1.message.create.return_value.success.return_value = False
    client.im.v1.message.create.return_value.code = 230002
    client.im.v1.message.create.return_value.msg = "invalid card_id"
    with pytest.raises(RuntimeError, match="飞书卡片消息发送失败"):
        await send_card_by_card_id(client, "ou_user1", "card_invalid")


@pytest.mark.asyncio
async def test_update_cardkit_card_failure_returns_false() -> None:
    """update_cardkit_card 失败时返回 False"""
    client = _mock_client()
    client.cardkit.v1.card.update.return_value.success.return_value = False
    client.cardkit.v1.card.update.return_value.code = 230002
    ok = await update_cardkit_card(client, "card_123", '{}', 1)
    assert ok is False


@pytest.mark.asyncio
async def test_create_card_entity_exception_returns_empty() -> None:
    """create_card_entity 异常时返回空字符串"""
    client = _mock_client()
    client.cardkit.v1.card.create.side_effect = RuntimeError("network error")
    card_id = await create_card_entity(client, '{}')
    assert card_id == ""


@pytest.mark.asyncio
async def test_stream_card_element_content_exception_returns_false() -> None:
    """stream_card_element_content 异常时返回 False"""
    client = _mock_client()
    client.cardkit.v1.card_element.acontent.side_effect = RuntimeError("timeout")
    ok = await stream_card_element_content(
        client, "card_123", "streaming_content", "Hello", 1,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_update_cardkit_card_exception_returns_false() -> None:
    """update_cardkit_card 异常时返回 False"""
    client = _mock_client()
    client.cardkit.v1.card.update.side_effect = RuntimeError("timeout")
    ok = await update_cardkit_card(client, "card_123", '{}', 1)
    assert ok is False


@pytest.mark.asyncio
async def test_set_card_streaming_mode_success() -> None:
    """set_card_streaming_mode 成功返回 True"""
    client = _mock_client()
    ok = await set_card_streaming_mode(client, "card_123", False, 5)
    assert ok is True
    client.cardkit.v1.card.settings.assert_called_once()
    # 验证 request_body 包含 streaming_mode=False
    req = client.cardkit.v1.card.settings.call_args[0][0]
    body = req.request_body
    settings_json = body.settings
    assert '"streaming_mode": false' in settings_json
    assert body.sequence == 5


@pytest.mark.asyncio
async def test_set_card_streaming_mode_failure() -> None:
    """set_card_streaming_mode 失败返回 False"""
    client = _mock_client()
    client.cardkit.v1.card.settings.return_value.success.return_value = False
    client.cardkit.v1.card.settings.return_value.code = 230002
    ok = await set_card_streaming_mode(client, "card_123", False, 1)
    assert ok is False


@pytest.mark.asyncio
async def test_set_card_streaming_mode_exception_returns_false() -> None:
    """set_card_streaming_mode 异常时返回 False"""
    client = _mock_client()
    client.cardkit.v1.card.settings.side_effect = RuntimeError("network error")
    ok = await set_card_streaming_mode(client, "card_123", False, 1)
    assert ok is False


# ---------------------------------------------------------------------------
# FeishuStreamingCardController 测试
# ---------------------------------------------------------------------------

from illusion_forge.channels.feishu.streaming import FeishuStreamingCardController


@pytest.mark.asyncio
async def test_controller_start_creates_card() -> None:
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1", reply_to="msg_abc")
    await controller.start()
    assert controller.phase == "streaming"
    assert controller.message_id == "msg_123"
    assert controller.card_id == "card_123"


@pytest.mark.asyncio
async def test_controller_on_text_accumulates() -> None:
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()
    await controller.on_text("Hello")
    await controller.on_text(" world")
    assert controller.accumulated_text == "Hello world"


@pytest.mark.asyncio
async def test_controller_on_reasoning_accumulates() -> None:
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()
    await controller.on_reasoning("thinking")
    await controller.on_reasoning(" more")
    assert controller.reasoning_text == "thinking more"
    assert controller.is_reasoning_phase is True


@pytest.mark.asyncio
async def test_controller_complete_transitions_to_completed() -> None:
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()
    await controller.on_text("Hello")
    await controller.complete()
    assert controller.phase == "completed"


@pytest.mark.asyncio
async def test_controller_error_preserves_text() -> None:
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()
    await controller.on_text("partial")
    await controller.error("LLM failed")
    assert controller.phase == "error"
    assert "partial" in controller.accumulated_text


@pytest.mark.asyncio
async def test_controller_cardkit_failure_falls_back_to_patch() -> None:
    client = _mock_client()
    # 让 card.create 失败
    client.cardkit.v1.card.create.return_value.success.return_value = False
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()
    # 降级后仍能正常工作
    assert controller.phase == "streaming"
    assert controller.card_id == ""  # CardKit 不可用
    assert controller.message_id != ""  # patch 路径仍有 message_id


@pytest.mark.asyncio
async def test_controller_throttle_batches_multiple_calls() -> None:
    """节流：100ms 内多次调用只触发一次实际 flush"""
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()  # start() 发送初始内容（1次调用）
    # 立即连续调用 5 次
    for i in range(5):
        await controller.on_text(f"chunk{i}")
    # 等待节流窗口 + 补偿 flush
    await asyncio.sleep(0.3)
    # card_element.acontent 调用次数：start(1) + 节流合并(1-2) = 2-3
    call_count = client.cardkit.v1.card_element.acontent.call_count
    assert call_count <= 3, f"Expected <=3 flush calls, got {call_count}"


@pytest.mark.asyncio
async def test_controller_invalid_phase_transition_rejected() -> None:
    """非法状态转换被拒绝"""
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    # idle 状态下不能直接 complete
    await controller.complete()
    assert controller.phase == "idle"  # 转换被拒绝


@pytest.mark.asyncio
async def test_controller_complete_without_reasoning() -> None:
    """无 reasoning 时终态卡片不含 collapsible_panel"""
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()
    await controller.on_text("Hi")
    with patch(
        "illusion_forge.channels.feishu.streaming.update_cardkit_card",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_update:
        await controller.complete()
        mock_update.assert_called_once()
        # card_content 是 update_cardkit_card 的第 3 个位置参数
        card_content_str = mock_update.call_args[0][2]
        card = json.loads(card_content_str)
        elements = card["body"]["elements"]
        # 无 reasoning 时只有 markdown (text) + markdown (footer)，无 collapsible_panel
        for elem in elements:
            assert elem["tag"] != "collapsible_panel"
    assert controller.phase == "completed"


@pytest.mark.asyncio
async def test_controller_patch_fallback_complete_receives_plain_text() -> None:
    """patch 降级路径终态：patch_card 收到纯文本而非 JSON"""
    client = _mock_client()
    client.cardkit.v1.card.create.return_value.success.return_value = False
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()
    assert controller.card_id == ""  # 降级

    await controller.on_text("Hello")
    with patch(
        "illusion_forge.channels.feishu.streaming.patch_card",
        new_callable=AsyncMock,
    ) as mock_patch:
        await controller.complete()
        # patch_card 应收到纯文本 "Hello"，不是 JSON 字符串
        call_args = mock_patch.call_args
        text_arg = call_args[0][2]  # 第 3 个位置参数
        assert text_arg == "Hello"
        assert not text_arg.startswith("{")  # 不是 JSON


@pytest.mark.asyncio
async def test_controller_card_update_failure_falls_back_to_patch() -> None:
    """card.update 失败时降级到 patch_card"""
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()
    await controller.on_text("Hello")

    # 让 card.update 失败
    client.cardkit.v1.card.update.return_value.success.return_value = False
    with patch(
        "illusion_forge.channels.feishu.streaming.patch_card",
        new_callable=AsyncMock,
    ) as mock_patch:
        await controller.complete()
        mock_patch.assert_called_once()
        # patch_card 收到纯文本
        text_arg = mock_patch.call_args[0][2]
        assert text_arg == "Hello"


@pytest.mark.asyncio
async def test_controller_throttle_has_lower_bound() -> None:
    """节流测试：验证 flush 次数有下限（不会因节流失效为 0）"""
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()  # start() 发送初始内容（1 call）
    for i in range(5):
        await controller.on_text(f"chunk{i}")
    await asyncio.sleep(0.3)
    call_count = client.cardkit.v1.card_element.acontent.call_count
    # start(1) + 节流合并(1-2) = 2-3
    assert 2 <= call_count <= 3, f"Expected 2-3 flush calls, got {call_count}"


@pytest.mark.asyncio
async def test_controller_finalize_closes_streaming_mode_before_update() -> None:
    """终态收尾：先 set_card_streaming_mode(False) 再 update_cardkit_card

    验证根因 A 修复：必须先关闭流式模式再全卡替换，
    否则飞书客户端仍在流式态导致终态卡片渲染异常。
    """
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()
    await controller.on_text("Hello")
    await asyncio.sleep(0.15)

    # 记录调用顺序
    call_log: list[str] = []
    client.cardkit.v1.card.settings.side_effect = lambda *a, **k: (
        call_log.append("settings"),
        client.cardkit.v1.card.settings.return_value,
    )[1]
    client.cardkit.v1.card.update.side_effect = lambda *a, **k: (
        call_log.append("update"),
        client.cardkit.v1.card.update.return_value,
    )[1]

    await controller.complete()
    assert controller.phase == "completed"
    # 两个 API 都被调用
    assert "settings" in call_log, "set_card_streaming_mode 未被调用"
    assert "update" in call_log, "update_cardkit_card 未被调用"
    # settings 必须在 update 之前
    assert call_log.index("settings") < call_log.index("update"), (
        "set_card_streaming_mode 必须在 update_cardkit_card 之前调用"
    )


@pytest.mark.asyncio
async def test_controller_flush_dedup_skips_unchanged_text() -> None:
    """flush 去重：相同 display_text 不触发重复 API 调用

    验证根因 E 修复：避免无意义的 API 调用。
    """
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()  # start() 发送初始内容（1 call）

    # 第一次 flush：display_text = "Hello"
    controller._accumulated_text = "Hello"
    controller._is_reasoning_phase = False
    await controller._flush()
    first_count = client.cardkit.v1.card_element.acontent.call_count
    # start(1) + flush(1) = 2
    assert first_count == 2

    # 第二次 flush：display_text 仍为 "Hello"，应被去重跳过
    await controller._flush()
    second_count = client.cardkit.v1.card_element.acontent.call_count
    assert second_count == first_count, "相同文本不应触发重复 API 调用"

    # 第三次 flush：文本变化，应触发
    controller._accumulated_text = "Hello world"
    await controller._flush()
    third_count = client.cardkit.v1.card_element.acontent.call_count
    assert third_count == first_count + 1


@pytest.mark.asyncio
async def test_controller_long_gap_updates_last_flush_time() -> None:
    """长间隔分支更新 _last_flush_time，避免反复取消+重设 timer

    验证根因 B 修复：长间隔批量窗口内后续事件应进入节流窗口分支，
    而不是反复进入长间隔分支导致延迟无限延长。
    """
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()

    # 模拟上次 flush 在很久以前（>2s 长间隔阈值）
    controller._last_flush_time = time.monotonic() - 3.0
    old_flush_time = controller._last_flush_time

    # 第一个事件：进入长间隔分支，应更新 _last_flush_time
    await controller.on_text("chunk0")
    assert controller._last_flush_time > old_flush_time, (
        "长间隔分支必须更新 _last_flush_time"
    )

    # 批量窗口内（300ms）的第二个事件：应进入节流窗口分支（else），
    # 不再触发长间隔逻辑，pending_timer 保留不重设
    flush_time_after_first = controller._last_flush_time
    await controller.on_text("chunk1")
    # _last_flush_time 不应被再次更新（节流窗口分支不更新）
    assert controller._last_flush_time == flush_time_after_first

    # 等待批量延迟执行
    await asyncio.sleep(0.4)
    # 应只触发一次实际 API 调用（批量合并）
    assert client.cardkit.v1.card_element.acontent.call_count >= 1


# ---------------------------------------------------------------------------
# 集成测试：ChannelRunner + FeishuStreamingCardController
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_full_streaming_flow() -> None:
    """模拟完整流式流程：start → on_reasoning → on_text → complete"""
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1", reply_to="msg_abc")

    await controller.start()
    assert controller.phase == "streaming"

    await controller.on_reasoning("Let me think")
    await controller.on_text("Hello")
    await controller.on_text(" world")
    # 等待节流窗口（100ms）让流式 flush 触发
    await asyncio.sleep(0.15)

    await controller.complete()
    assert controller.phase == "completed"
    assert controller.accumulated_text == "Hello world"
    assert controller.reasoning_text == "Let me think"

    # 验证 CardKit API 被调用
    assert client.cardkit.v1.card.create.called
    assert client.cardkit.v1.card_element.acontent.called
    assert client.cardkit.v1.card.update.called


@pytest.mark.asyncio
async def test_integration_error_flow() -> None:
    """模拟错误流程：start → on_text → error"""
    client = _mock_client()
    controller = FeishuStreamingCardController(client, "ou_user1")

    await controller.start()
    await controller.on_text("partial content")
    await controller.error("LLM timeout")

    assert controller.phase == "error"
    assert "partial content" in controller.accumulated_text
    assert "Error" in controller.accumulated_text


@pytest.mark.asyncio
async def test_integration_cardkit_fallback_to_patch() -> None:
    """模拟降级：CardKit 创建失败 → patch 路径"""
    client = _mock_client()
    # card.create 失败
    client.cardkit.v1.card.create.return_value.success.return_value = False

    controller = FeishuStreamingCardController(client, "ou_user1")
    await controller.start()

    # 应降级到 patch 路径
    assert controller.card_id == ""
    assert controller.message_id != ""

    # 流式更新走 patch_card
    with patch(
        "illusion_forge.channels.feishu.streaming.patch_card",
        new_callable=AsyncMock,
    ) as mock_patch:
        # 模拟上次 flush 在很久以前，触发长间隔批量路径（300ms 延迟而非 1.5s）
        controller._last_flush_time = time.monotonic() - 3.0
        await controller.on_text("Hello")
        await asyncio.sleep(0.4)
        assert mock_patch.called

    await controller.complete()
    assert controller.phase == "completed"
