"""
版本同步脚本测试
================
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# 直接加载脚本模块
script_path = Path(__file__).parent.parent.parent / "scripts" / "sync_version.py"
spec = importlib.util.spec_from_file_location("sync_version", script_path)
sync_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_version)


def test_read_version_from_pyproject() -> None:
    """测试从 pyproject.toml 读取版本号"""
    version = sync_version.read_version_from_pyproject()
    assert version is not None
    assert isinstance(version, str)
    # 验证版本号格式（x.y.z）
    parts = version.split(".")
    assert len(parts) == 3
    for part in parts:
        assert part.isdigit()


def test_generate_web_version_file(tmp_path: Path) -> None:
    """测试生成 Web 前端版本文件"""
    # 创建临时目录结构
    frontend_dir = tmp_path / "frontend" / "web" / "src"
    frontend_dir.mkdir(parents=True)

    # 修改函数的输出路径
    original_func = sync_version.generate_web_version_file

    def mock_generate(version: str) -> None:
        content = f"export const VERSION = '{version}';\n"
        output_path = frontend_dir / "version.ts"
        output_path.write_text(content, encoding="utf-8")

    sync_version.generate_web_version_file = mock_generate

    try:
        sync_version.generate_web_version_file("1.2.3")
        version_file = frontend_dir / "version.ts"
        assert version_file.exists()
        content = version_file.read_text(encoding="utf-8")
        assert "1.2.3" in content
    finally:
        sync_version.generate_web_version_file = original_func


def test_update_package_json_version(tmp_path: Path) -> None:
    """测试更新 package.json 版本号"""
    import json

    # 创建临时 package.json
    package_path = tmp_path / "package.json"
    package_data = {"name": "test", "version": "1.0.0"}
    package_path.write_text(json.dumps(package_data, indent=2), encoding="utf-8")

    # 测试更新版本号
    sync_version.update_package_json_version(package_path, "2.0.0")

    with package_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == "2.0.0"

    # 测试版本号已经是最新的情况
    sync_version.update_package_json_version(package_path, "2.0.0")
    with package_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == "2.0.0"
