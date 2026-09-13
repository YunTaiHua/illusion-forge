"""max-tokens 斜杠指令单元测试"""
import pytest

from illusion_forge.commands.settings import max_tokens_handler
from illusion_forge.config.i18n import t


@pytest.mark.asyncio
async def test_max_tokens_show(fake_context):
    """show 子命令返回当前值"""
    result = await max_tokens_handler("show", fake_context)
    assert t("max_tokens_show", value=16384) in result.message


@pytest.mark.asyncio
async def test_max_tokens_set_preset(fake_context):
    """预设档位 8k 设置成功"""
    result = await max_tokens_handler("8k", fake_context)
    assert "8192" in result.message
    assert fake_context.engine.max_tokens == 8192


@pytest.mark.asyncio
async def test_max_tokens_set_number(fake_context):
    """数字直接设置成功"""
    result = await max_tokens_handler("131072", fake_context)
    assert "131072" in result.message
    assert fake_context.engine.max_tokens == 131072


@pytest.mark.asyncio
async def test_max_tokens_invalid(fake_context):
    """非法值返回 usage"""
    result = await max_tokens_handler("invalid", fake_context)
    assert t("max_tokens_usage") in result.message
