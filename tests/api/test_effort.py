"""EffortMapper 单元测试模块

本模块提供 EffortMapper 类的单元测试，包括：
- effort 级别标准化测试
- 降级映射测试
- 反向映射测试
"""

import pytest

from illusion_forge.api.effort import EffortLevel, EffortMapper


class TestEffortLevel:
    """EffortLevel 枚举测试"""

    def test_effort_level_values(self):
        """测试 EffortLevel 枚举值"""
        assert EffortLevel.LOW == "low"
        assert EffortLevel.MEDIUM == "medium"
        assert EffortLevel.HIGH == "high"
        assert EffortLevel.XHIGH == "xhigh"
        assert EffortLevel.MAX == "max"

    def test_effort_level_from_string(self):
        """测试从字符串创建 EffortLevel"""
        assert EffortLevel("low") == EffortLevel.LOW
        assert EffortLevel("medium") == EffortLevel.MEDIUM
        assert EffortLevel("high") == EffortLevel.HIGH
        assert EffortLevel("xhigh") == EffortLevel.XHIGH
        assert EffortLevel("max") == EffortLevel.MAX

    def test_effort_level_invalid_string(self):
        """测试无效字符串抛出 ValueError"""
        with pytest.raises(ValueError):
            EffortLevel("invalid")


class TestEffortMapper:
    """EffortMapper 类测试"""

    def test_normalize_string(self):
        """测试字符串标准化"""
        assert EffortMapper.normalize("low") == EffortLevel.LOW
        assert EffortMapper.normalize("MEDIUM") == EffortLevel.MEDIUM
        assert EffortMapper.normalize("High") == EffortLevel.HIGH

    def test_normalize_effort_level(self):
        """测试 EffortLevel 标准化"""
        assert EffortMapper.normalize(EffortLevel.LOW) == EffortLevel.LOW
        assert EffortMapper.normalize(EffortLevel.MEDIUM) == EffortLevel.MEDIUM

    def test_fallback_low_to_high(self):
        """测试 low 降级到 high"""
        supported = {EffortLevel.HIGH}
        assert EffortMapper.fallback(EffortLevel.LOW, supported) == EffortLevel.HIGH

    def test_fallback_medium_to_high(self):
        """测试 medium 降级到 high"""
        supported = {EffortLevel.HIGH}
        assert EffortMapper.fallback(EffortLevel.MEDIUM, supported) == EffortLevel.HIGH

    def test_fallback_high_unchanged(self):
        """测试 high 保持不变"""
        supported = {EffortLevel.HIGH}
        assert EffortMapper.fallback(EffortLevel.HIGH, supported) == EffortLevel.HIGH

    def test_fallback_xhigh_to_max(self):
        """测试 xhigh 降级到 max"""
        supported = {EffortLevel.MAX}
        assert EffortMapper.fallback(EffortLevel.XHIGH, supported) == EffortLevel.MAX

    def test_fallback_max_unchanged(self):
        """测试 max 保持不变"""
        supported = {EffortLevel.MAX}
        assert EffortMapper.fallback(EffortLevel.MAX, supported) == EffortLevel.MAX

    def test_fallback_all_supported(self):
        """测试所有级别都支持时的降级"""
        supported = {EffortLevel.LOW, EffortLevel.MEDIUM, EffortLevel.HIGH, EffortLevel.XHIGH, EffortLevel.MAX}
        assert EffortMapper.fallback(EffortLevel.LOW, supported) == EffortLevel.LOW
        assert EffortMapper.fallback(EffortLevel.MEDIUM, supported) == EffortLevel.MEDIUM
        assert EffortMapper.fallback(EffortLevel.HIGH, supported) == EffortLevel.HIGH
        assert EffortMapper.fallback(EffortLevel.XHIGH, supported) == EffortLevel.XHIGH
        assert EffortMapper.fallback(EffortLevel.MAX, supported) == EffortLevel.MAX

    def test_reverse_fallback_max_to_xhigh(self):
        """测试 max 反向降级到 xhigh"""
        assert EffortMapper.reverse_fallback(EffortLevel.MAX) == EffortLevel.XHIGH

    def test_reverse_fallback_xhigh_to_max(self):
        """测试 xhigh 反向降级到 max（链式降级的第一步）"""
        assert EffortMapper.reverse_fallback(EffortLevel.XHIGH) == EffortLevel.MAX

    def test_reverse_fallback_high_unchanged(self):
        """测试 high 反向降级保持不变"""
        assert EffortMapper.reverse_fallback(EffortLevel.HIGH) == EffortLevel.HIGH

    def test_reverse_fallback_low_unchanged(self):
        """测试 low 反向降级保持不变"""
        assert EffortMapper.reverse_fallback(EffortLevel.LOW) == EffortLevel.LOW

    def test_reverse_fallback_medium_unchanged(self):
        """测试 medium 反向降级保持不变"""
        assert EffortMapper.reverse_fallback(EffortLevel.MEDIUM) == EffortLevel.MEDIUM

    def test_fallback_xhigh_to_high_when_max_not_supported(self):
        """测试 xhigh 降级到 high（当 max 不支持时）"""
        supported = {EffortLevel.HIGH}
        assert EffortMapper.fallback(EffortLevel.XHIGH, supported) == EffortLevel.HIGH

    def test_fallback_max_to_high_when_xhigh_not_supported(self):
        """测试 max 降级到 high（当 xhigh 不支持时）"""
        supported = {EffortLevel.HIGH}
        assert EffortMapper.fallback(EffortLevel.MAX, supported) == EffortLevel.HIGH

    def test_fallback_xhigh_to_max_when_supported(self):
        """测试 xhigh 降级到 max（当 max 支持时）"""
        supported = {EffortLevel.HIGH, EffortLevel.MAX}
        assert EffortMapper.fallback(EffortLevel.XHIGH, supported) == EffortLevel.MAX

    def test_fallback_max_to_xhigh_when_supported(self):
        """测试 max 降级到 xhigh（当 xhigh 支持时）"""
        supported = {EffortLevel.HIGH, EffortLevel.XHIGH}
        assert EffortMapper.fallback(EffortLevel.MAX, supported) == EffortLevel.XHIGH
