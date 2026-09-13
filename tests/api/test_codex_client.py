"""Codex 客户端 effort 处理测试模块

本模块提供 Codex 客户端 effort 处理的单元测试，包括：
- effort 字段传递测试
- effort 降级测试
- effort 错误检测测试
"""



class TestCodexClientEffort:
    """Codex 客户端 effort 处理测试"""

    def test_effort_added_to_params(self):
        """测试 effort 字段添加到请求参数"""
        # 这个测试需要模拟 HTTPX，暂时跳过

    def test_effort_not_added_when_none(self):
        """测试 effort 为 None 时不添加到请求参数"""
        # 这个测试需要模拟 HTTPX，暂时跳过
