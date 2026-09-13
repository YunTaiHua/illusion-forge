"""
会话压缩模块常量定义。
"""

from __future__ import annotations

# 可压缩的工具列表
COMPACTABLE_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "bash",
    "grep",
    "glob",
    "web_search",
    "web_fetch",
    "edit_file",
    "write_file",
})

# 微压缩清除后的占位符消息
TIME_BASED_MC_CLEARED_MESSAGE = "[Old tool result content cleared]"

# 自动压缩阈值
AUTOCOMPACT_BUFFER_TOKENS = 13_000
WARNING_THRESHOLD_BUFFER_TOKENS = 20_000
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3
MANUAL_COMPACT_BUFFER_TOKENS = 3_000

# 微压缩默认值
DEFAULT_KEEP_RECENT = 5
DEFAULT_GAP_THRESHOLD_MINUTES = 60
DEFAULT_PRESERVE_RECENT = 6

# Token 估算 padding（保守估计）
TOKEN_ESTIMATION_PADDING = 4 / 3

# 默认上下文窗口大小
_DEFAULT_CONTEXT_WINDOW = 200_000

# PTL 重试最大次数
MAX_PTL_RETRIES = 3

# 压缩边界标记前缀
COMPACT_BOUNDARY_PREFIX = "[COMPACT_BOUNDARY]"

# 不使用工具的前导文本
NO_TOOLS_PREAMBLE = """\
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use read_file, bash, grep, glob, edit_file, write_file, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.

"""

# 基础压缩提示词
BASE_COMPACT_PROMPT = """\
Your task is to create a detailed summary of the conversation so far. This summary will replace the earlier messages, so it must capture all important information.

First, draft your analysis inside <analysis> tags. Walk through the conversation chronologically and extract:
- Every user request and intent (explicit and implicit)
- The approach taken and technical decisions made
- Specific code, files, and configurations discussed (with paths and line numbers where available)
- All errors encountered and how they were fixed
- Any user feedback or corrections

Then, produce a structured summary inside <summary> tags with these sections:

1. **Primary Request and Intent**: All user requests in full detail, including nuances and constraints.
2. **Key Technical Concepts**: Technologies, frameworks, patterns, and conventions discussed.
3. **Files and Code Sections**: Every file examined or modified, with specific code snippets and line numbers.
4. **Errors and Fixes**: Every error encountered, its cause, and how it was resolved.
5. **Problem Solving**: Problems solved and approaches that worked vs. didn't work.
6. **All User Messages**: Non-tool-result user messages (preserve exact wording for context).
7. **Pending Tasks**: Explicitly requested work that hasn't been completed yet.
8. **Current Work**: Detailed description of the last task being worked on before compaction.
9. **Optional Next Step**: The single most logical next step, directly aligned with the user's recent request.
"""

# 不使用工具的结尾文本
NO_TOOLS_TRAILER = """
REMINDER: Do NOT call any tools. Respond with plain text only — an <analysis> block followed by a <summary> block. Tool calls will be rejected and you will fail the task."""
