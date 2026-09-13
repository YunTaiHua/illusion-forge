"""LSP 管理器测试。"""

from __future__ import annotations

from pathlib import Path

from illusion_forge.services.lsp.config import LspServerConfig
from illusion_forge.services.lsp.manager import LspManager


class TestLspManager:
    """LspManager 路由和生命周期测试。"""

    def test_ext_map_construction(self):
        configs = {
            "python": LspServerConfig(command="pyright", args=[], extensions=[".py", ".pyi"]),
            "go": LspServerConfig(command="gopls", args=[], extensions=[".go"]),
        }
        manager = LspManager(configs)
        assert manager._ext_map[".py"] == "python"
        assert manager._ext_map[".pyi"] == "python"
        assert manager._ext_map[".go"] == "go"

    def test_get_language_id(self):
        configs = {
            "python": LspServerConfig(command="pyright", args=[], extensions=[".py"]),
            "typescript": LspServerConfig(command="tsserver", args=[], extensions=[".ts", ".tsx"]),
        }
        manager = LspManager(configs)
        assert manager.get_language_id(Path("main.py")) == "python"
        assert manager.get_language_id(Path("app.ts")) == "typescript"
        assert manager.get_language_id(Path("page.tsx")) == "typescript"
        assert manager.get_language_id(Path("readme.md")) is None

    def test_supported_extensions(self):
        configs = {
            "python": LspServerConfig(command="pyright", args=[], extensions=[".py"]),
            "go": LspServerConfig(command="gopls", args=[], extensions=[".go"]),
        }
        manager = LspManager(configs)
        exts = manager.supported_extensions
        assert ".py" in exts
        assert ".go" in exts
        assert ".md" not in exts
