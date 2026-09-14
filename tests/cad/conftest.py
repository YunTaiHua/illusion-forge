"""CAD 测试共享夹具：缺 COM 依赖的环境（如 CI runner）注入最小桩模块。

vendor 层（sw_connect 等）在模块导入期执行 ``import_com_dependencies()``，
pywin32/comtypes 缺失时会走交互式 pip 安装确认（``input()``），在 pytest
捕获 stdin 的环境下直接抛 OSError。本目录测试用 Fake COM 对象驱动、不发起
真实 COM 调用，因此只需让"依赖可导入"即可。

注意：桩模块必须在 **conftest 导入时** 注入（而非 autouse fixture）。
pytest 收集测试模块时会立即执行模块顶层 import，此时 fixture 尚未运行；
若等到 fixture 再打桩，CI 上 ``from pywintypes import com_error`` 会先炸。
仅当真实依赖缺失时注入桩，开发机上已装 pywin32 不受影响。
"""
from __future__ import annotations

import importlib.util
import sys
import types


class _ComStubError(Exception):
    """替代 pywin32 的 com_error，供 vendor 层异常分支捕获。"""


class _FakeVARIANT:
    """替代 win32com.client.VARIANT（测试内不构造真实 VARIANT）。"""


def _make_stub(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    if name == "pywintypes":
        module.com_error = _ComStubError
    elif name == "pythoncom":
        module.CoInitialize = lambda *args, **kwargs: None
        module.CoUninitialize = lambda *args, **kwargs: None
        module.com_error = _ComStubError
    elif name == "win32com.client":
        module.VARIANT = _FakeVARIANT
    return module


def _module_missing(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is None
    except (ImportError, ValueError):
        return True


# 桩模块清单：win32com/comtypes 需同时注册父包与子模块，
# 并把子模块挂到父包属性上，保证 `import win32com.client` 等写法可用
_STUB_NAMES = (
    "pywintypes",
    "pythoncom",
    "win32com",
    "win32com.client",
    "comtypes",
    "comtypes.client",
)


def _install_com_stubs_if_missing() -> None:
    missing = [name for name in _STUB_NAMES if _module_missing(name)]
    if not missing:
        return
    stubs = {name: _make_stub(name) for name in _STUB_NAMES}
    for name in missing:
        sys.modules.setdefault(name, stubs[name])
        if "." in name:
            parent, child = name.rsplit(".", 1)
            stubs[parent].__dict__[child] = stubs[name]


# conftest 加载即打桩：早于 tests/cad 下任意测试模块的顶层 import
_install_com_stubs_if_missing()
