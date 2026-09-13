#!/usr/bin/env python3
"""
图标构建脚本
=============

从 desktop/build/assets/ 的源图标生成 Windows 桌面壳所需图标到 desktop/build/：
  - icon.ico：多分辨率 ICO（安装包 / exe / 任务栏 / 系统通知）
  - icon.png：512x512 PNG（窗口图标兜底）

同时复制一份 512 png 到 desktop/resources/icon.png，作为运行时托盘图标
（打包后由 extraResources 放入 Resources/，运行时 process.resourcesPath/icon.png）。

用法：python scripts/build_icons.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

DESKTOP_ROOT = Path(__file__).resolve().parent.parent / "desktop"
ASSETS = DESKTOP_ROOT / "build" / "assets"
BUILD = DESKTOP_ROOT / "build"
RESOURCES = DESKTOP_ROOT / "resources"


def build_ico_from_pngs() -> bool:
    """从 assets/ 下的多分辨率 PNG 合成 icon.ico，写入 build/ 和 assets/

    用 Pillow 编码（dev 依赖，见 pyproject dev extras）：小尺寸（<256）以
    32bit BMP 存储、主图 256 打底，是 Windows 最常见且兼容性最好的 ICO
    布局。此前"全部尺寸直接嵌 PNG 字节"的写法会被 electron-builder 注入
    exe 时丢弃 16px，导致系统通知/toast 的小图标回退成通用占位。
    """
    try:
        from PIL import Image
    except ImportError:
        print(
            "错误: 生成 icon.ico 需要 Pillow，请安装 dev 依赖后重试"
            "（pip install -e .[dev] 或 pip install Pillow）",
            file=sys.stderr,
        )
        return False

    sizes = [16, 32, 64, 128, 256]
    images: list[Image.Image] = []
    for size in sizes:
        path = ASSETS / f"icon_{size}x{size}.png"
        if not path.exists():
            print(f"警告: 缺少 {path.name}", file=sys.stderr)
            return False
        images.append(Image.open(path).convert("RGBA"))

    ico_path = BUILD / "icon.ico"
    # Pillow ICO 编码：sizes 声明目标尺寸，主图取最大尺寸（Pillow 只处理
    # <= 主图尺寸的 size），其余尺寸经 append_images 原样嵌入（尺寸一一
    # 对应不缩放）；bitmap_format="bmp" 让条目以 DIB 存储，避免 PNG 压缩
    # 的小尺寸条目在 electron-builder 注入 exe 时被丢弃。
    images[-1].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
        bitmap_format="bmp",
    )
    shutil.copy2(ico_path, ASSETS / "icon.ico")
    print(f"icon.ico ({len(images)} resolutions, {ico_path.stat().st_size} bytes)")
    return True


def main() -> None:
    if not ASSETS.exists():
        print(f"图标源目录不存在：{ASSETS}", file=sys.stderr)
        sys.exit(1)

    BUILD.mkdir(parents=True, exist_ok=True)
    RESOURCES.mkdir(parents=True, exist_ok=True)

    # --- 从多分辨率 PNG 合成 ico ---
    if not build_ico_from_pngs():
        # 回退：直接复制旧 ico
        ico_src = ASSETS / "icon.ico"
        if ico_src.exists():
            shutil.copy2(ico_src, BUILD / "icon.ico")
            print("icon.ico (fallback copy)")
        else:
            print("错误: 无法生成 icon.ico", file=sys.stderr)
            sys.exit(1)

    # --- 窗口图标兜底 / 运行时托盘: 复制 512 png ---
    png512 = ASSETS / "icon_512x512.png"
    if png512.exists():
        shutil.copy2(png512, BUILD / "icon.png")
        shutil.copy2(png512, RESOURCES / "icon.png")
        shutil.copy2(png512, ASSETS / "icon.png")
        print("icon.png (build + resources + assets)")
    else:
        print("警告: 未找到源 icon_512x512.png", file=sys.stderr)


if __name__ == "__main__":
    main()
