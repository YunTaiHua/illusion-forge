"""
内置工具注册模块
================

本模块提供 IllusionForge 内置工具的注册和管理功能。

主要组件：
    - BaseTool: 工具抽象基类
    - ToolExecutionContext: 工具执行上下文
    - ToolResult: 工具执行结果
    - ToolRegistry: 工具注册表
    - create_default_tool_registry: 创建默认工具注册表

使用示例：
    >>> from illusion_forge.tools import create_default_tool_registry, ToolRegistry
    >>> registry = create_default_tool_registry()
"""

from typing import Any

from illusion_forge.tools.agent_tool import AgentTool
from illusion_forge.tools.ask_user_question_tool import AskUserQuestionTool
from illusion_forge.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from illusion_forge.tools.bash_tool import BashTool
from illusion_forge.tools.config_tool import ConfigTool
from illusion_forge.tools.cron_tool import CronTool
from illusion_forge.tools.enter_plan_mode_tool import EnterPlanModeTool
from illusion_forge.tools.enter_worktree_tool import EnterWorktreeTool
from illusion_forge.tools.exit_plan_mode_tool import ExitPlanModeTool
from illusion_forge.tools.exit_worktree_tool import ExitWorktreeTool
from illusion_forge.tools.file_edit_tool import FileEditTool
from illusion_forge.tools.file_read_tool import FileReadTool
from illusion_forge.tools.file_write_tool import FileWriteTool
from illusion_forge.tools.glob_tool import GlobTool
from illusion_forge.tools.goal_tools import CreateGoalTool, GetGoalTool, UpdateGoalTool
from illusion_forge.tools.grep_tool import GrepTool
from illusion_forge.tools.list_mcp_resources_tool import ListMcpResourcesTool
from illusion_forge.tools.list_sessions_tool import ListSessionsTool
from illusion_forge.tools.lsp_tool import LspTool
from illusion_forge.tools.mcp_auth_tool import McpAuthTool
from illusion_forge.tools.mcp_tool import McpToolAdapter
from illusion_forge.tools.powershell_tool import PowerShellTool
from illusion_forge.tools.read_mcp_resource_tool import ReadMcpResourceTool
from illusion_forge.tools.send_message_tool import SendMessageTool
from illusion_forge.tools.skill_tool import SkillTool
from illusion_forge.tools.sleep_tool import SleepTool
from illusion_forge.tools.task_output_tool import TaskOutputTool
from illusion_forge.tools.task_stop_tool import TaskStopTool
from illusion_forge.tools.team_create_tool import TeamCreateTool
from illusion_forge.tools.team_delete_tool import TeamDeleteTool
from illusion_forge.tools.todo_write_tool import TodoWriteTool
from illusion_forge.tools.web_fetch_tool import WebFetchTool
from illusion_forge.tools.web_search_tool import WebSearchTool


def create_default_tool_registry(
    mcp_manager: Any = None,
    channel_tools: list[BaseTool[Any]] | None = None,
    goal_enabled: bool = False,
    cad_enabled: bool = False,
) -> ToolRegistry:
    """返回默认内置工具注册表

    Args:
        mcp_manager: MCP 管理器（可选）
        channel_tools: 渠道内置工具列表（可选，渠道启用时由调用方传入）
        goal_enabled: 是否注册 goal 工具（settings.goal.enabled；goal 属根
            会话，工具经引擎的 tool_metadata 拿到 GoalManager）
        cad_enabled: 是否注册 CAD 工作台工具域（按会话类型传入：
            工作台会话 True；关闭时不注册 cad_*/canvas_* 工具，也不导入 cad 包）

    Returns:
        ToolRegistry: 工具注册表
    """
    registry = ToolRegistry()
    tools: list[BaseTool[Any]] = [
        BashTool(),
        PowerShellTool(),
        AskUserQuestionTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        LspTool(),
        McpAuthTool(),
        GlobTool(),
        GrepTool(),
        SkillTool(),
        WebFetchTool(),
        WebSearchTool(),
        ConfigTool(),
        SleepTool(),
        EnterWorktreeTool(),
        ExitWorktreeTool(),
        TodoWriteTool(),
        EnterPlanModeTool(),
        ExitPlanModeTool(),
        ListSessionsTool(),
        CronTool(),
        TaskStopTool(),
        TaskOutputTool(),
        AgentTool(),
        SendMessageTool(),
        TeamCreateTool(),
        TeamDeleteTool(),
    ]
    if goal_enabled:
        # goal 工具（get_goal/create_goal/update_goal）
        tools.extend([GetGoalTool(), CreateGoalTool(), UpdateGoalTool()])
    for tool in tools:
        registry.register(tool)
    if cad_enabled:
        # CAD 工作台工具域（cad_health_check / cad_preview_build / canvas_*）：
        # 懒导入，关闭时零开销且不触发 pywin32/OCP 等依赖探测
        from illusion_forge.cad.tools import create_cad_tools

        for tool in create_cad_tools():
            registry.register(tool)
    if mcp_manager is not None:
        registry.register(ListMcpResourcesTool(mcp_manager))
        registry.register(ReadMcpResourceTool(mcp_manager))
        for tool_info in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_manager, tool_info))
    # 注册渠道内置工具（飞书文档/云盘等，渠道启用时由调用方传入）
    if channel_tools:
        for tool in channel_tools:
            registry.register(tool)
    return registry


__all__ = [
    "BaseTool",
    "ToolExecutionContext",
    "ToolRegistry",
    "ToolResult",
    "create_default_tool_registry",
]
