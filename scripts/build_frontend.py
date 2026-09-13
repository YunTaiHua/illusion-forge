#!/usr/bin/env python3
"""
前端构建脚本
============

构建 web 前端的预编译产物（Vite build），输出到 frontend/web/dist。

用法：
    python scripts/build_frontend.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve_cmd(cmd: list[str]) -> list[str]:
    """Windows 上将 .cmd/.bat 路径补全，避免 WinError 193。"""
    if sys.platform == "win32" and not cmd[0].endswith((".cmd", ".bat", ".exe")):
        for ext in (".cmd", ".bat", ".exe"):
            candidate = cmd[0] + ext
            if Path(candidate).exists():
                cmd = [candidate] + cmd[1:]
                break
    return cmd


def _fix_node_env(npm_path: str) -> dict[str, str]:
    """将 npm 所在目录插入 PATH 前面，确保 npm.cmd 内部找到正确的 node.exe。

    某些环境（如通过 pip 安装的 nodejs-wheel 包）会在 Python Scripts
    目录中放置一个假的 node.exe，导致 npm.cmd 内部调用 node 时失败。
    """
    npm_dir = str(Path(npm_path).parent)
    env = dict(os.environ)
    current_path = env.get("PATH", "")
    if not current_path.startswith(npm_dir):
        env["PATH"] = npm_dir + ";" + current_path
    return env


def _find_node() -> str:
    """查找 node 可执行文件路径。"""
    node = shutil.which("node")
    if node is None:
        print("ERROR: Node.js is not installed or not in PATH.", file=sys.stderr)
        print("  Please install Node.js 18+ from https://nodejs.org/", file=sys.stderr)
        sys.exit(1)
    return node


def _find_npm() -> str:
    """查找 npm 可执行文件路径。"""
    npm = shutil.which("npm")
    if npm is None:
        print("ERROR: npm is not installed or not in PATH.", file=sys.stderr)
        sys.exit(1)
    return npm


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    """运行命令并检查返回码。"""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd), env=env)
    if result.returncode != 0:
        print(f"ERROR: Command failed with exit code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


def _ensure_deps(frontend_dir: Path, npm: str) -> None:
    """如果 node_modules 不存在则运行 npm install。"""
    if not (frontend_dir / "node_modules").exists():
        print(f"  Installing dependencies in {frontend_dir.name}...")
        cmd = _resolve_cmd([npm, "install", "--no-fund", "--no-audit"])
        env = _fix_node_env(npm)
        _run(cmd, frontend_dir, env=env)
    else:
        print(f"  Dependencies already installed in {frontend_dir.name}.")


def build_web(npm: str) -> None:
    """构建 web 前端（Vite build）。"""
    frontend_dir = REPO_ROOT / "frontend" / "web"
    if not (frontend_dir / "package.json").exists():
        print(f"ERROR: Web frontend not found at {frontend_dir}", file=sys.stderr)
        sys.exit(1)

    print("\n=== Building web frontend ===")
    _ensure_deps(frontend_dir, npm)
    _run(_resolve_cmd([npm, "run", "build"]), frontend_dir, env=_fix_node_env(npm))

    index_html = frontend_dir / "dist" / "index.html"
    if index_html.exists():
        print(f"  OK: {frontend_dir / 'dist'}")
    else:
        print("ERROR: Build output not found: dist/index.html", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    _find_node()
    npm = _find_npm()
    build_web(npm)
    print("\nBuild completed.")


if __name__ == "__main__":
    main()
