"""commands 测试公共 fixture"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_context():
    """构造一个假的 CommandContext 用于测试"""
    ctx = MagicMock()
    ctx.app_state.get.return_value.max_tokens = 16384
    ctx.engine.max_tokens = 16384
    ctx.cwd = "."
    ctx.channel_hint = None
    return ctx
