"""项目扫描器测试"""

from pathlib import Path

from illusion_forge.commands.init.extraction.scanner import scan_project


def test_scan_python_project(tmp_path: Path):
    """测试扫描 Python 项目"""
    # 创建项目结构
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_main(): pass\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\ndependencies = ["flask"]\n\n'
        '[tool.ruff]\nline-length = 88\n'
    )
    (tmp_path / "README.md").write_text("# Test Project\n\nA test project.\n")
    (tmp_path / ".gitignore").write_text("__pycache__/\n")

    data = scan_project(tmp_path)

    assert "Python" in data.languages
    assert data.languages["Python"] >= 2
    assert "Flask" in data.frameworks
    assert data.package_manager is not None
    assert data.readme_summary is not None


def test_scan_js_project(tmp_path: Path):
    """测试扫描 JS 项目"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export function main() {}\n")
    (tmp_path / "src" / "app.tsx").write_text("export default function App() {}\n")
    (tmp_path / "package.json").write_text(
        '{"name": "test", "scripts": {"build": "tsc", "test": "jest"}, '
        '"dependencies": {"react": "^18.0.0"}, "devDependencies": {"jest": "^29.0.0"}}'
    )
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
    (tmp_path / "package-lock.json").write_text('{}')

    data = scan_project(tmp_path)

    assert "TypeScript" in data.languages or "React" in data.languages
    assert "React" in data.frameworks
    assert data.package_manager == "npm"
    assert len(data.build_commands) > 0
    assert len(data.test_commands) > 0


def test_scan_empty_project(tmp_path: Path):
    """测试扫描空项目"""
    data = scan_project(tmp_path)
    assert data.languages == {}
    assert data.frameworks == []
    assert data.package_manager is None
