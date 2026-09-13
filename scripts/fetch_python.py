#!/usr/bin/env python3
"""
内置 Python 运行时下载脚本
============================

从 astral-sh/python-build-standalone 下载 Windows install_only 发行版，
解压到 desktop/resources/python/win-<arch>/。

用法：
    python scripts/fetch_python.py                  # 默认 3.12.13
    python scripts/fetch_python.py --version 3.11.9

下载源：https://github.com/astral-sh/python-build-standalone/releases
解压使用 Python 标准库 tarfile。

路径约定：
    DESKTOP_ROOT = desktop/
    输出: DESKTOP_ROOT/resources/python/win-<arch>/
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import platform
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DESKTOP_ROOT = Path(__file__).resolve().parent.parent / "desktop"
RESOURCES = DESKTOP_ROOT / "resources"

DEFAULT_VERSION = "3.12.13"

# python-build-standalone 命名约定的 Windows 平台三元组
TRIPLE_MAP = {
    "x64": "x86_64-pc-windows-msvc",
    "arm64": "aarch64-pc-windows-msvc",
}


def host_arch() -> str:
    """当前主机架构，规范化为 x64 / arm64（桌面壳仅支持 Windows）。"""
    if sys.platform != "win32":
        print(f"仅支持在 Windows 上构建桌面版，当前平台：{sys.platform}", file=sys.stderr)
        sys.exit(1)
    mach = platform.machine().lower()
    return "arm64" if mach in ("arm64", "aarch64") else "x64"


def triple() -> str:
    """平台三元组（python-build-standalone 命名约定）"""
    return TRIPLE_MAP[host_arch()]


def plat_arch() -> str:
    """桌面壳内部用的平台-arch 标识（与 runtime.ts platArch 保持一致）"""
    return f"win-{host_arch()}"


def _http_get_json(url: str, headers: dict[str, str], retries: int = 3) -> list[dict]:
    """带重试的 GitHub API GET，返回 JSON 列表。

    GitHub API 的 releases 响应较大（含全部 asset 元数据），CI 网络抖动
    时 resp.read() 可能 IncompleteRead 截断，重试可显著降低失败率。
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as resp:
                if resp.status != 200:
                    print(f"GitHub API 请求失败：{resp.status}", file=sys.stderr)
                    sys.exit(1)
                data = json.loads(resp.read())
            if isinstance(data, list):
                return data
            print("GitHub API 返回格式异常", file=sys.stderr)
            sys.exit(1)
        except (urllib.error.URLError, http.client.IncompleteRead, ConnectionError, TimeoutError, OSError) as exc:
            last_exc = exc
            print(f"GitHub API 请求失败（第 {attempt + 1}/{retries} 次）：{exc}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    print(f"GitHub API 多次请求均失败：{last_exc}", file=sys.stderr)
    sys.exit(1)


def _download_with_retry(url: str, dest: Path, retries: int = 3) -> None:
    """带重试的文件下载（大文件传输中断时重试）。"""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            urllib.request.urlretrieve(url, dest)
            return
        except (urllib.error.URLError, http.client.IncompleteRead, ConnectionError, TimeoutError, OSError) as exc:
            last_exc = exc
            print(f"下载失败（第 {attempt + 1}/{retries} 次）：{exc}", file=sys.stderr)
            dest.unlink(missing_ok=True)
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    print(f"下载多次失败：{last_exc}", file=sys.stderr)
    sys.exit(1)


def find_asset(version: str) -> tuple[str, str]:
    """查 GitHub release 找匹配 version + 平台的 install_only asset"""
    triple_str = triple()
    suffix = f"{triple_str}-install_only.tar.gz"
    url = "https://api.github.com/repos/astral-sh/python-build-standalone/releases?per_page=20"
    headers = {"User-Agent": "illusion-forge-desktop"}
    # CI 环境用 GITHUB_TOKEN 认证，提高 API 限流额度（匿名 60/小时 → 认证 5000/小时）
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    releases = _http_get_json(url, headers)
    for rel in releases:
        for asset in rel.get("assets", []):
            name = asset["name"]
            if f"cpython-{version}" in name and name.endswith(suffix):
                return asset["browser_download_url"], name
    print(f"未找到 Python {version} 的 {triple_str} install_only 资产", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="下载内置 Python 运行时")
    parser.add_argument("--version", default=DEFAULT_VERSION, help=f"Python 版本（默认 {DEFAULT_VERSION}）")
    args = parser.parse_args()

    url, name = find_asset(args.version)
    out_dir = RESOURCES / "python" / plat_arch()
    out_dir.mkdir(parents=True, exist_ok=True)
    tarball = out_dir / name

    print(f"下载 {name}\n  {url}")
    _download_with_retry(url, tarball)

    print(f"解压到 {out_dir}")
    with tarfile.open(tarball, "r:gz") as tf:
        # filter='tar'：拒绝绝对路径/.. 但保留 symlinks（install_only 含 python3→python3.12 等符号链接）
        tf.extractall(out_dir, filter='tar')

    tarball.unlink()
    print(f"Python {args.version} -> {out_dir}")


if __name__ == "__main__":
    main()
