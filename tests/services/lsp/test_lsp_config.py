"""LSP 配置模块测试。"""

from __future__ import annotations

from illusion_forge.services.lsp.config import LspServerConfig, load_lsp_config


class TestLspServerConfig:
    """LspServerConfig 数据类测试。"""

    def test_default_values(self):
        config = LspServerConfig(command="pyright-langserver", args=["--stdio"], extensions=[".py"])
        assert config.command == "pyright-langserver"
        assert config.args == ["--stdio"]
        assert config.extensions == [".py"]
        assert config.env is None
        assert config.initialization_options is None
        assert config.settings is None
        assert config.startup_timeout == 30

    def test_custom_values(self):
        config = LspServerConfig(
            command="gopls",
            args=[],
            extensions=[".go"],
            env={"GOPATH": "/custom"},
            startup_timeout=60,
        )
        assert config.command == "gopls"
        assert config.env == {"GOPATH": "/custom"}
        assert config.startup_timeout == 60


class TestLoadLspConfig:
    """load_lsp_config 测试。"""

    def test_returns_all_defaults(self):
        configs = load_lsp_config(None)
        assert "python" in configs
        assert "typescript" in configs
        assert "go" in configs
        assert "rust" in configs
        assert "cpp" in configs
        assert configs["python"].command == "pyright-langserver"

    def test_user_override_replaces_default(self, tmp_path):
        settings = {
            "lsp_servers": {
                "python": {
                    "command": "pylsp",
                    "args": [],
                    "extensions": [".py"],
                }
            }
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(__import__("json").dumps(settings), encoding="utf-8")

        configs = load_lsp_config(settings_file)
        assert configs["python"].command == "pylsp"

    def test_user_can_add_new_language(self, tmp_path):
        settings = {
            "lsp_servers": {
                "java": {
                    "command": "jdtls",
                    "args": [],
                    "extensions": [".java"],
                }
            }
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(__import__("json").dumps(settings), encoding="utf-8")

        configs = load_lsp_config(settings_file)
        assert "java" in configs
        assert configs["java"].command == "jdtls"
        # 原有语言不受影响
        assert "python" in configs
