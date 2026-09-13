"""测试中断/异常场景下运行时层合成 tool_result 的行为。

覆盖 _synthesize_pending_tool_results 辅助函数和 query.py 中的异常处理器。
DeepSeek 等 strict provider 要求每个 tool_use 必须有对应的 tool_result，
否则返回 400 "tool_use ids were found without tool_result"。
"""
import inspect

from illusion_forge.engine import query as query_module
from illusion_forge.engine.messages import ConversationMessage, ToolResultBlock, ToolUseBlock
from illusion_forge.engine.query import _synthesize_pending_tool_results


class TestSynthesizePendingToolResults:
    """_synthesize_pending_tool_results 单元测试。"""

    def test_all_pending(self):
        """所有工具都未完成 → 全部合成错误结果。"""
        tool_calls = [
            ToolUseBlock(id="c1", name="read_file", input={}),
            ToolUseBlock(id="c2", name="bash", input={}),
        ]
        results: list[ToolResultBlock | None] = []
        synth = _synthesize_pending_tool_results(
            tool_calls, results,
            error_message_fn=lambda name: f"Tool {name} interrupted",
        )
        assert len(synth) == 2
        assert all(r.is_error for r in synth)
        assert synth[0].tool_use_id == "c1"
        assert synth[0].content == "Tool read_file interrupted"
        assert synth[1].tool_use_id == "c2"
        assert synth[1].content == "Tool bash interrupted"

    def test_partial_pending(self):
        """部分工具已完成 → 保留已完成结果，合成未完成的。"""
        tool_calls = [
            ToolUseBlock(id="c1", name="read_file", input={}),
            ToolUseBlock(id="c2", name="bash", input={}),
        ]
        done_result = ToolResultBlock(tool_use_id="c1", content="file content")
        results: list[ToolResultBlock | None] = [done_result]
        synth = _synthesize_pending_tool_results(
            tool_calls, results,
            error_message_fn=lambda name: f"Tool {name} interrupted",
        )
        assert len(synth) == 2
        # 已完成的保留原结果
        assert synth[0] is done_result
        assert synth[0].content == "file content"
        assert not synth[0].is_error
        # 未完成的合成错误
        assert synth[1].tool_use_id == "c2"
        assert synth[1].content == "Tool bash interrupted"
        assert synth[1].is_error

    def test_all_done(self):
        """所有工具都已完成 → 不合成任何结果。"""
        tool_calls = [
            ToolUseBlock(id="c1", name="read_file", input={}),
        ]
        done_result = ToolResultBlock(tool_use_id="c1", content="ok")
        results: list[ToolResultBlock | None] = [done_result]
        synth = _synthesize_pending_tool_results(
            tool_calls, results,
            error_message_fn=lambda name: f"Tool {name} interrupted",
        )
        assert len(synth) == 1
        assert synth[0] is done_result

    def test_empty_tool_calls(self):
        """无工具调用 → 返回空列表。"""
        synth = _synthesize_pending_tool_results(
            [], [],
            error_message_fn=lambda name: f"Tool {name} interrupted",
        )
        assert synth == []

    def test_custom_error_message_fn(self):
        """自定义错误消息回调（如 PermissionDenied 场景）。"""
        tool_calls = [ToolUseBlock(id="c1", name="bash", input={})]
        results: list[ToolResultBlock | None] = []
        synth = _synthesize_pending_tool_results(
            tool_calls, results,
            error_message_fn=lambda name: f"Permission denied for {name}",
        )
        assert synth[0].content == "Permission denied for bash"

    def test_does_not_mutate_input_list(self):
        """入参列表不应被修改（无隐式副作用）。"""
        tool_calls = [
            ToolUseBlock(id="c1", name="t1", input={}),
            ToolUseBlock(id="c2", name="t2", input={}),
            ToolUseBlock(id="c3", name="t3", input={}),
        ]
        results: list[ToolResultBlock | None] = [
            ToolResultBlock(tool_use_id="c1", content="ok"),
        ]
        original_len = len(results)
        synth = _synthesize_pending_tool_results(
            tool_calls, results,
            error_message_fn=lambda name: f"Tool {name} interrupted",
        )
        # 返回值长度与 tool_calls 一致
        assert len(synth) == 3
        # 入参列表未被修改
        assert len(results) == original_len
        assert results == [ToolResultBlock(tool_use_id="c1", content="ok")]


class TestQueryExceptionHandlers:
    """验证 query.py 中异常处理器的源码结构。

    由于 run_query 是异步生成器且依赖大量上下文，这里用源码检查方式验证
    关键行为（与现有 test_query_permission.py 风格一致）。
    """

    def test_keyboard_interrupt_handler_exists(self):
        """KeyboardInterrupt/CancelledError handler 存在且合成 tool_result。"""
        source = inspect.getsource(query_module)
        assert "except (KeyboardInterrupt, asyncio.CancelledError)" in source, \
            "query.py 应捕获 KeyboardInterrupt 和 CancelledError"
        # 找到该 handler 块
        idx = source.index("except (KeyboardInterrupt, asyncio.CancelledError)")
        block = source[idx:]
        # 截取到下一个 except 或 def
        for marker in ["\n        except ", "\n    def ", "\n\nclass ", "\n\nasync def "]:
            pos = block.find(marker, 1)
            if pos > 0:
                block = block[:pos]
                break
        assert "_synthesize_pending_tool_results" in block, \
            "中断 handler 应调用 _synthesize_pending_tool_results"
        assert "messages.append" in block, \
            "中断 handler 应将合成结果追加到 messages"
        assert "raise" in block, \
            "中断 handler 应重新抛出异常"

    def test_exception_handler_exists(self):
        """通用 Exception handler 存在且合成 tool_result。"""
        source = inspect.getsource(query_module)
        # 确保不再使用 except BaseException
        assert "except BaseException" not in source, \
            "query.py 不应使用 except BaseException（已收窄为具体异常类型）"
        # 找到通用 Exception handler（最后的兜底处理器，无 noqa 注释）
        idx = source.index("except Exception:")
        block = source[idx:]
        for marker in ["\n        except ", "\n    def ", "\n\nclass ", "\n\nasync def "]:
            pos = block.find(marker, 1)
            if pos > 0:
                block = block[:pos]
                break
        assert "_synthesize_pending_tool_results" in block, \
            "Exception handler 应调用 _synthesize_pending_tool_results"
        assert "messages.append" in block, \
            "Exception handler 应将合成结果追加到 messages"
        assert "raise" in block, \
            "Exception handler 应重新抛出异常"

    def test_permission_denied_handler_uses_helper(self):
        """PermissionDenied handler 使用提取的辅助函数。"""
        source = inspect.getsource(query_module)
        idx = source.index("except PermissionDenied as exc:")
        block = source[idx:]
        for marker in ["\n        except ", "\n    def ", "\n\nclass ", "\n\nasync def "]:
            pos = block.find(marker, 1)
            if pos > 0:
                block = block[:pos]
                break
        assert "_synthesize_pending_tool_results" in block, \
            "PermissionDenied handler 应调用 _synthesize_pending_tool_results"

    def test_no_base_exception_anymore(self):
        """确保不再有 except BaseException。"""
        source = inspect.getsource(query_module)
        # 不应出现 except BaseException（已收窄）
        assert "except BaseException" not in source, \
            "query.py 中不应再有 except BaseException"


class TestSynthesizePreservesMessageConsistency:
    """验证合成结果能保持消息历史一致性。

    模拟 run_query 中断后 messages 的状态：assistant(tool_use) 后必须
    紧跟 user(tool_result)，否则下一轮 _convert_messages_to_openai
    会触发合成（但理想情况下运行时层已补齐）。
    """

    def test_synth_results_pair_with_tool_uses(self):
        """合成结果与 tool_use 配对，转换层无需再补齐。"""
        from illusion_forge.api.openai_client import _convert_messages_to_openai

        tool_calls = [
            ToolUseBlock(id="call_1", name="bash", input={}),
            ToolUseBlock(id="call_2", name="read_file", input={}),
        ]
        # 模拟中断：两个工具都未完成
        synth = _synthesize_pending_tool_results(
            tool_calls, [],
            error_message_fn=lambda name: f"Tool {name} interrupted",
        )
        # 构造消息历史：assistant(tool_use) → user(synth tool_result)
        messages = [
            ConversationMessage.from_user_text("run two tools"),
            ConversationMessage(role="assistant", content=tool_calls),
            ConversationMessage(role="user", content=synth),
        ]
        result = _convert_messages_to_openai(messages, None)
        # 不应有任何合成的 "Tool execution interrupted"（运行时层已处理）
        fallback = [m for m in result if m.get("content") == "Tool execution interrupted"]
        assert fallback == [], "运行时层已合成 tool_result，转换层不应再补齐"

    def test_synth_partial_results_pair_with_tool_uses(self):
        """部分完成的合成结果也能与 tool_use 正确配对。"""
        from illusion_forge.api.openai_client import _convert_messages_to_openai

        tool_calls = [
            ToolUseBlock(id="call_1", name="bash", input={}),
            ToolUseBlock(id="call_2", name="read_file", input={}),
        ]
        # 第一个工具完成，第二个中断
        done = ToolResultBlock(tool_use_id="call_1", content="output")
        synth = _synthesize_pending_tool_results(
            tool_calls, [done],
            error_message_fn=lambda name: f"Tool {name} interrupted",
        )
        messages = [
            ConversationMessage(role="assistant", content=tool_calls),
            ConversationMessage(role="user", content=synth),
        ]
        result = _convert_messages_to_openai(messages, None)
        # 两个 tool_result 都应存在，无转换层兜底合成
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        ids = {m["tool_call_id"] for m in tool_msgs}
        assert ids == {"call_1", "call_2"}
        fallback = [m for m in result if m.get("content") == "Tool execution interrupted"]
        assert fallback == []
