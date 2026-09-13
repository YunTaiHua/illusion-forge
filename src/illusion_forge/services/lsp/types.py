"""
统一数据模型
============

语言无关的符号和模块数据结构，替代原有的 PythonModuleInfo 和 SymbolLocation。
使用标准 LSP SymbolKind 枚举。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class SymbolKind(Enum):
    """标准 LSP SymbolKind 枚举。"""

    FILE = 1
    MODULE = 2
    NAMESPACE = 3
    PACKAGE = 4
    CLASS = 5
    METHOD = 6
    PROPERTY = 7
    FIELD = 8
    CONSTRUCTOR = 9
    ENUM = 10
    INTERFACE = 11
    FUNCTION = 12
    VARIABLE = 13
    CONSTANT = 14
    STRING = 15
    NUMBER = 16
    BOOLEAN = 17
    ARRAY = 18
    OBJECT = 19
    KEY = 20
    NULL = 21
    ENUM_MEMBER = 22
    STRUCT = 23
    EVENT = 24
    OPERATOR = 25
    TYPE_PARAMETER = 26


@dataclass(frozen=True)
class SymbolInfo:
    """语言无关的符号信息。"""

    name: str
    kind: SymbolKind
    path: Path
    line: int
    character: int
    signature: str = ""
    docstring: str = ""
    container: str = ""


@dataclass
class ModuleInfo:
    """语言无关的模块信息。"""

    path: Path
    language: str  # "python", "typescript", "go", "rust", "cpp"
    docstring: str | None
    symbols: list[SymbolInfo]
    imports: list[str]
    dependencies: list[str] = field(default_factory=list)
