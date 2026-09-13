"""
Glob 工具 - 使用 ripgrep 列出匹配的文件。

核心原则：让 rg 去碰文件系统，Python 只处理结果。
"""

from pydantic import BaseModel, Field

from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolResult
from illusion_forge.utils.ripgrep import run_rg_checked


class GlobToolInput(BaseModel):
    """Glob工具的参数模型

    Attributes:
        pattern: 相对于工作目录的glob模式
        root: 可选的搜索根目录
        limit: 返回结果数量限制
    """

    pattern: str = Field(description="Glob pattern relative to the working directory")
    root: str | None = Field(default=None, description="Optional search root")
    limit: int = Field(default=200, ge=1, le=5000)


def split_absolute_glob_pattern(pattern: str) -> tuple[str, str]:
    """
    拆分绝对路径 glob 模式为根路径和相对模式。

    Args:
        pattern: 绝对路径 glob 模式，如 "E:/repo/**/*.py"

    Returns:
        (根路径, 相对模式) 元组
    """
    # 查找第一个通配符
    wildcard_chars = ["*", "?", "[", "{"]
    min_idx = len(pattern)
    for char in wildcard_chars:
        idx = pattern.find(char)
        if idx != -1 and idx < min_idx:
            min_idx = idx

    # 查找最后一个路径分隔符（在通配符之前）
    last_sep = -1
    for i in range(min_idx - 1, -1, -1):
        if pattern[i] in ("/", "\\"):
            last_sep = i
            break

    if last_sep == -1:
        return ".", pattern

    root = pattern[:last_sep]
    relative = pattern[last_sep + 1:]

    # 处理 Windows 驱动器号
    if len(root) == 2 and root[1] == ":":
        root = root + "\\"

    return root, relative


class GlobTool(BaseTool[GlobToolInput]):
    """列出匹配glob模式的文件

    使用说明：
    - 快速的文件模式匹配工具，适用于任何规模的代码库
    - 支持glob模式如 "**/*.js" 或 "src/**/*.ts"
    - 返回按修改时间排序的匹配文件路径
    - 当需要按名称模式查找文件时使用此工具
    - 当进行开放性搜索可能需要多轮glob和grep时，使用Agent工具
    """

    name = "glob"
    description = """- Fast file pattern matching tool that works with any codebase size
- Supports glob patterns like "**/*.js" or "src/**/*.ts"
- Returns matching file paths sorted by modification time
- Use this tool when you need to find files by name patterns
- When you are doing an open ended search that may require multiple rounds of globbing and grepping, use the Agent tool instead"""
    input_model = GlobToolInput

    def is_read_only(self, arguments: GlobToolInput) -> bool:
        """返回工具是否为只读操作

        Args:
            arguments: 工具输入参数

        Returns:
            bool: 始终返回True，glob是只读操作
        """
        del arguments
        return True

    async def execute(self, arguments: GlobToolInput, context: ToolExecutionContext) -> ToolResult:
        """执行glob搜索

        Args:
            arguments: 工具输入参数
            context: 工具执行上下文

        Returns:
            ToolResult: 搜索结果
        """
        pattern = arguments.pattern
        path = arguments.root

        # 处理绝对路径模式
        if not path and (":\\" in pattern or pattern.startswith("/")):
            path, pattern = split_absolute_glob_pattern(pattern)
        elif not path:
            path = "."

        # 构建 rg 参数
        args = ["--files"]

        # 默认包含隐藏文件
        args.append("--hidden")

        # 默认不尊重 .gitignore
        args.append("--no-ignore")

        # Glob 模式
        args.extend(["--glob", pattern])

        # 排除 VCS 目录
        for vcs in [".git", ".svn", ".hg", ".bzr", ".jj", ".sl"]:
            args.extend(["--glob", f"!{vcs}"])

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

        # 规范化路径：移除 rg 在 Windows 上添加的 .\ 或 ./ 前缀
        lines = [
            line[2:] if line.startswith((".\\", "./")) else line
            for line in lines
        ]

        # 限制结果数量
        limit = arguments.limit
        if limit and len(lines) > limit:
            lines = lines[:limit]

        return ToolResult(output="\n".join(lines))
