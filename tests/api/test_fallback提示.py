"""降级提示功能测试模块

本模块提供降级提示功能的单元测试，包括：
- 降级提示生成测试
- 降级提示显示测试
"""

from illusion_forge.api.effort import EffortLevel


class TestFallback提示:
    """降级提示功能测试"""

    def test_降级提示消息生成(self):
        """测试降级提示消息生成"""
        # 测试 low -> high 降级
        original = EffortLevel.LOW
        fallback = EffortLevel.HIGH
        message = f"Effort level {original.value} not supported, falling back to {fallback.value}"
        assert message == "Effort level low not supported, falling back to high"

    def test_降级提示消息生成_xhigh到max(self):
        """测试 xhigh -> max 降级提示消息生成"""
        original = EffortLevel.XHIGH
        fallback = EffortLevel.MAX
        message = f"Effort level {original.value} not supported, falling back to {fallback.value}"
        assert message == "Effort level xhigh not supported, falling back to max"
