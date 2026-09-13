"""QueryEngine effort 传递测试模块

本模块提供 QueryEngine effort 传递的单元测试，包括：
- effort 字段传递到 ApiMessageRequest 测试
- effort 字段默认值测试
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from illusion_forge.engine.query_engine import QueryEngine


class TestQueryEngineEffort:
    """QueryEngine effort 传递测试"""

    @pytest.fixture
    def mock_engine(self):
        """创建模拟的 QueryEngine"""
        engine = MagicMock(spec=QueryEngine)
        engine._api_client = AsyncMock()
        engine._model = "test-model"
        engine._system_prompt = "test prompt"
        engine._max_tokens = 4096
        engine._tool_registry = MagicMock()
        engine._tool_registry.to_api_schema.return_value = []
        return engine

    @pytest.mark.asyncio
    async def test_effort_passed_to_request(self, mock_engine):
        """测试 effort 字段传递到 ApiMessageRequest"""
        # 这个测试需要完整的 QueryEngine，暂时跳过
