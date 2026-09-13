"""
Grep 工具 - 使用 ripgrep 搜索文件内容。

核心原则：让 rg 去碰文件系统，Python 只处理结果。
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult
from illusion_forge.utils.ripgrep import run_rg_checked


class GrepToolInput(BaseModel):
    """Grep工具的参数模型

    Attributes:
        pattern: 要搜索的正则表达式
        path: 要搜索的文件或目录
        glob: 文件过滤glob（如 "*.js", "**/*.tsx"）
        output_mode: 输出模式：content显示匹配行，files_with_matches只显示文件路径（默认），count显示匹配计数
        context_before: 匹配前的行数
        context_after: 匹配后的行数
        context: 匹配周围的行数（覆盖-B/-A）
        case_sensitive: 是否区分大小写
        type: rg --type 过滤器（如 "js", "py", "rust"）
        multiline: 启用多行匹配（rg -U --multiline-dotall）
        head_limit: 最大结果数（0=无限制）
        offset: 跳过前N个结果
    """

    pattern: str = Field(description="Regular expression to search for")
    path: str | None = Field(default=None, description="File or directory to search")
    glob: str | None = Field(default=None, description='File filter glob (e.g., "*.js", "**/*.tsx")')
    output_mode: Literal["content", "files_with_matches", "count"] = Field(
        default="files_with_matches",
        description="Output mode: content shows matching lines, files_with_matches shows only file paths (default), count shows match counts",
    )
    context_before: int | None = Field(default=None, description="Lines before match")
    context_after: int | None = Field(default=None, description="Lines after match")
    context: int | None = Field(default=None, description="Lines around match (overrides -B/-A)")
    case_sensitive: bool = Field(default=True, description="Case sensitive search")
    type: str | None = Field(default=None, description='rg --type filter (e.g., "js", "py", "rust")')
    multiline: bool = Field(default=False, description="Enable multiline matching (rg -U --multiline-dotall)")
    head_limit: int = Field(default=250, ge=0, description="Max results (0 = unlimited)")
    offset: int = Field(default=0, ge=0, description="Skip first N results")


class GrepTool(BaseTool[GrepToolInput]):
    """搜索文本文件的正则表达式模式

    使用说明：
    - 始终使用Grep进行搜索任务。永远不要调用Bash命令中的grep或rg。Grep工具已针对正确的权限和访问进行优化
    - 支持完整正则表达式语法（如 "log.*Error", "function\\s+\\w+"）
    - 使用glob参数过滤文件（如 "*.js", "**/*.tsx"）或type参数（如 "js", "py", "rust"）
    - 输出模式："content"显示匹配行，"files_with_matches"只显示文件路径（默认），"count"显示匹配计数
    - 对于需要多轮搜索的开放性搜索使用Agent工具
    - 模式语法：使用ripgrep（不是grep）- 字面大括号需要转义（使用 `interface\\{\\}` 在Go代码中查找 `interface{}`）
    - 多行匹配：默认模式仅在单行内匹配。对于跨行模式如 `struct \\{[\\s\\S]*?field`，使用 `multiline: true`
    """

    name = "grep"
    description = """A powerful search tool built on ripgrep

Usage:
- ALWAYS use Grep for search tasks. NEVER invoke `grep` or `rg` as a Bash command. The Grep tool has been optimized for correct permissions and access.
- Supports full regex syntax (e.g., "log.*Error", "function\\s+\\w+")
- Filter files with glob parameter (e.g., "*.js", "**/*.tsx") or type parameter (e.g., "js", "py", "rust")
- Output modes: "content" shows matching lines, "files_with_matches" shows only file paths (default), "count" shows match counts
- Use Agent tool for open-ended searches requiring multiple rounds
- Pattern syntax: Uses ripgrep (not grep) - literal braces need escaping (use `interface\\{\\}` to find `interface{}` in Go code)
- Multiline matching: By default patterns match within single lines only. For cross-line patterns like `struct \\{[\\s\\S]*?field`, use `multiline: true`"""
    input_model = GrepToolInput

    def is_read_only(self, arguments: GrepToolInput) -> bool:
        """返回工具是否为只读操作

        Args:
            arguments: 工具输入参数

        Returns:
            bool: 始终返回True，grep是只读操作
        """
        del arguments
        return True

    async def execute(self, arguments: GrepToolInput, context: ToolExecutionContext) -> ToolResult:
        """执行grep搜索

        Args:
            arguments: 工具输入参数
            context: 工具执行上下文

        Returns:
            ToolResult: 搜索结果
        """
        path = arguments.path or "."

        # 构建 rg 参数
        args = ["--hidden"]

        # 排除 VCS 目录
        for vcs in [".git", ".svn", ".hg", ".bzr", ".jj", ".sl"]:
            args.extend(["--glob", f"!{vcs}"])

        # 行长限制
        args.extend(["--max-columns", "500"])

        # 大小写
        if not arguments.case_sensitive:
            args.append("-i")

        # 多行模式
        if arguments.multiline:
            args.extend(["-U", "--multiline-dotall"])

        # 输出模式
        if arguments.output_mode == "files_with_matches":
            args.append("-l")
        elif arguments.output_mode == "count":
            args.append("-c")
        else:
            args.append("-n")  # 行号

        # 上下文行
        context_lines = arguments.context or 0
        if context_lines:
            args.extend(["-C", str(context_lines)])
        else:
            if arguments.context_before is not None:
                args.extend(["-B", str(arguments.context_before)])
            if arguments.context_after is not None:
                args.extend(["-A", str(arguments.context_after)])

        # 文件类型
        if arguments.type:
            args.extend(["--type", arguments.type])

        # Glob 过滤
        if arguments.glob:
            # 保持大括号模式如 *.{ts,tsx} 完整
            parts = arguments.glob.split()
            for part in parts:
                args.extend(["--glob", part])

        # 搜索模式（以 - 开头的模式用 -e 前缀）
        pattern = arguments.pattern

        # 预校验正则表达式，避免无效正则触发 RipgrepError 异常链导致后端崩溃。
        # rg.exe 对无效正则返回非零退出码，会被包装为 RipgrepError 抛出，
        # 单工具路径下该异常会逃逸 _safe_run 保护，最终让进程崩溃。
        try:
            re.compile(pattern)
        except re.error as exc:
            return ToolResult(
                output=f"Invalid regex pattern: {exc}",
                is_error=True,
            )

        if pattern.startswith("-"):
            args.extend(["-e", pattern])
        else:
            args.append(pattern)

        # 搜索路径
        args.append(path)

        # 使用 run_rg_checked 避免 RipgrepError 在单工具路径下逃逸 _safe_run
        # 导致后端崩溃；rg 的所有失败统一转为 ToolResult(is_error=True)。
        stdout, error_msg = await run_rg_checked(args, cwd=str(context.cwd))
        if error_msg is not None:
            return ToolResult(output=error_msg, is_error=True)

        # 退出码 1 表示无匹配（run_rg_checked 返回空字符串）
        if not stdout:
            return ToolResult(output="(no matches)")

        # 解析结果
        lines = stdout.strip().split("\n")
        if not lines or (len(lines) == 1 and not lines[0]):
            return ToolResult(output="(no matches)")

        # 应用分页
        offset = arguments.offset
        head_limit = arguments.head_limit
        if offset > 0:
            lines = lines[offset:]
        if head_limit > 0 and len(lines) > head_limit:
            lines = lines[:head_limit]

        return ToolResult(output="\n".join(lines))
