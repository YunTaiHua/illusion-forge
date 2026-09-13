"""
LSP 工具输入 Schema
===================

同时支持 camelCase 和 snake_case 操作名（向后兼容）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# camelCase -> snake_case 映射
_OPERATION_ALIASES: dict[str, str] = {
    "go_to_definition": "goToDefinition",
    "find_references": "findReferences",
    "document_symbol": "documentSymbol",
    "workspace_symbol": "workspaceSymbol",
    "go_to_implementation": "goToImplementation",
    "prepare_call_hierarchy": "prepareCallHierarchy",
    "incoming_calls": "incomingCalls",
    "outgoing_calls": "outgoingCalls",
}


class LspToolInput(BaseModel):
    """LSP 工具输入参数。"""

    operation: Literal[
        "goToDefinition",
        "findReferences",
        "hover",
        "documentSymbol",
        "workspaceSymbol",
        "goToImplementation",
        "prepareCallHierarchy",
        "incomingCalls",
        "outgoingCalls",
        "activate",
        # snake_case 兼容
        "go_to_definition",
        "find_references",
        "document_symbol",
        "workspace_symbol",
        "go_to_implementation",
        "prepare_call_hierarchy",
        "incoming_calls",
        "outgoing_calls",
    ] = Field(description="The LSP operation to perform")

    filePath: str = Field(
        default="",
        description="The absolute or relative path to the file",
    )

    query: str = Field(
        default="",
        description="Search query for workspaceSymbol operation",
    )

    line: int = Field(
        default=0,
        description="The line number (1-based, as shown in editors)",
        ge=0,
    )

    character: int = Field(
        default=0,
        description="The character offset (1-based, as shown in editors)",
        ge=0,
    )

    @field_validator("operation", mode="before")
    @classmethod
    def normalize_operation(cls, v: str) -> str:
        """将 snake_case 操作名转换为 camelCase。"""
        return _OPERATION_ALIASES.get(v, v)
