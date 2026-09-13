"""ApiMessageRequest effort 字段测试模块

本模块提供 ApiMessageRequest 类 effort 字段的单元测试，包括：
- effort 字段默认值测试
- effort 字段设置测试
- effort 字段序列化测试
"""

from illusion_forge.api.client import ApiMessageRequest
from illusion_forge.api.effort import EffortLevel
from illusion_forge.engine.messages import ConversationMessage


class TestApiMessageRequestEffort:
    """ApiMessageRequest effort 字段测试"""

    def test_effort_default_value(self):
        """测试 effort 字段默认值"""
        request = ApiMessageRequest(
            model="test-model",
            messages=[ConversationMessage.from_user_text("test")],
        )
        assert request.effort is None

    def test_effort_set_valid_value(self):
        """测试设置有效的 effort 值"""
        request = ApiMessageRequest(
            model="test-model",
            messages=[ConversationMessage.from_user_text("test")],
            effort=EffortLevel.HIGH,
        )
        assert request.effort == EffortLevel.HIGH

    def test_effort_set_xhigh(self):
        """测试设置 xhigh effort 值"""
        request = ApiMessageRequest(
            model="test-model",
            messages=[ConversationMessage.from_user_text("test")],
            effort=EffortLevel.XHIGH,
        )
        assert request.effort == EffortLevel.XHIGH

    def test_effort_set_max(self):
        """测试设置 max effort 值"""
        request = ApiMessageRequest(
            model="test-model",
            messages=[ConversationMessage.from_user_text("test")],
            effort=EffortLevel.MAX,
        )
        assert request.effort == EffortLevel.MAX
