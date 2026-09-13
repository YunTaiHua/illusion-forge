"""统一数据模型测试。"""

from __future__ import annotations

from pathlib import Path

from illusion_forge.services.lsp.types import ModuleInfo, SymbolInfo, SymbolKind


class TestSymbolKind:
    """SymbolKind 枚举测试。"""

    def test_standard_values(self):
        assert SymbolKind.CLASS.value == 5
        assert SymbolKind.FUNCTION.value == 12
        assert SymbolKind.METHOD.value == 6
        assert SymbolKind.VARIABLE.value == 13
        assert SymbolKind.INTERFACE.value == 11

    def test_from_lsp_value(self):
        assert SymbolKind(5) == SymbolKind.CLASS
        assert SymbolKind(12) == SymbolKind.FUNCTION


class TestSymbolInfo:
    """SymbolInfo 数据类测试。"""

    def test_create_minimal(self):
        sym = SymbolInfo(
            name="foo",
            kind=SymbolKind.FUNCTION,
            path=Path("src/main.py"),
            line=10,
            character=0,
        )
        assert sym.name == "foo"
        assert sym.kind == SymbolKind.FUNCTION
        assert sym.signature == ""
        assert sym.docstring == ""
        assert sym.container == ""

    def test_create_full(self):
        sym = SymbolInfo(
            name="bar",
            kind=SymbolKind.METHOD,
            path=Path("src/mod.py"),
            line=42,
            character=4,
            signature="def bar(self, x: int) -> str",
            docstring="Do something.",
            container="MyClass",
        )
        assert sym.container == "MyClass"
        assert sym.signature == "def bar(self, x: int) -> str"

    def test_frozen(self):
        sym = SymbolInfo(name="x", kind=SymbolKind.VARIABLE, path=Path("a.py"), line=1, character=0)
        try:
            sym.name = "y"  # type: ignore[misc]
            assert False, "Should be frozen"
        except AttributeError:
            pass


class TestModuleInfo:
    """ModuleInfo 数据类测试。"""

    def test_create(self):
        mod = ModuleInfo(
            path=Path("src/main.py"),
            language="python",
            docstring="Main module",
            symbols=[],
            imports=["os", "sys"],
            dependencies=["requests"],
        )
        assert mod.language == "python"
        assert len(mod.imports) == 2
