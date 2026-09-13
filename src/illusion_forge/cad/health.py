"""CAD 工作台环境健康检查（M1 范围）。

只报告事实，不做能力门禁：SolidWorks 的 COM 附着/建模能力在 M2
（STA 宿主线程）接入，此处先给出环境事实供 agent 与用户决策。

SolidWorks 探测使用标准库 winreg 读注册表（不依赖 pywin32），
非 Windows 平台安全降级。
"""

from __future__ import annotations

import importlib.util
import platform
from pathlib import Path
from typing import Any


def detect_solidworks() -> dict[str, Any]:
    """尽力探测本机 SolidWorks 安装（注册表，不启动进程）。"""
    result: dict[str, Any] = {"installed": False, "versions": []}
    if platform.system() != "Windows":
        result["detail"] = "非 Windows 平台，COM 自动化不可用"
        return result
    try:
        import winreg
    except ImportError:
        result["detail"] = "winreg 不可用"
        return result
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\SOLIDWORKS"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\SOLIDWORKS"),
    ]
    versions: set[str] = set()
    for hive, path in roots:
        try:
            with winreg.OpenKey(hive, path) as key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    if subkey_name.upper().startswith("SOLIDWORKS"):
                        versions.add(subkey_name)
        except OSError:
            continue
    # ProgID 注册检查（COM 附着的前提）
    progid_ok = False
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "SldWorks.Application"):
            progid_ok = True
    except OSError:
        pass
    result["installed"] = bool(versions) or progid_ok
    result["versions"] = sorted(versions)
    result["progid_registered"] = progid_ok
    return result


def collect_health(artifacts_dir: Path) -> dict[str, Any]:
    """收集 CAD 工作台环境健康报告。

    Args:
        artifacts_dir: 产物根目录（用于可写性检查）

    Returns:
        dict: {platform, solidworks, dependencies, artifacts_dir}
    """
    dependencies = {
        name: importlib.util.find_spec(name) is not None
        for name in ("win32com", "comtypes", "OCP", "ezdxf")
    }
    try:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        writable = True
    except OSError:
        writable = False
    return {
        "platform": platform.system(),
        "solidworks": detect_solidworks(),
        "dependencies": dependencies,
        "artifacts_dir": str(artifacts_dir),
        "artifacts_dir_writable": writable,
    }
