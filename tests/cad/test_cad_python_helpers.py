"""cad_python 逃生舱辅助函数回归测试（2026-09-13 花键轴会话错误级联的固化）。

该会话中 cad_python 连续报错的三类根因：

1. 工具描述与错误提示承诺 ``safe_gcm(obj, '成员名', default=None)``，但
   ``safe_get_com_member`` 不接受 ``default`` → TypeError。
2. pywin32 动态派发下无参方法的裸属性访问即执行并返回结果（如
   ``feat.GetTypeName2`` 直接得到类型名字符串），再加括号调用就报
   ``'str' object is not callable``；``gcm`` 必须原样返回该结果。
3. 取特征内的草图只能用 ``GetSpecificFeature2``，提示必须点名该方法，
   避免会话里 ``feat.Sketch`` 连续 AttributeError 的盲试。

全部用 Fake COM 对象驱动，不启动真实 SolidWorks。
"""

from __future__ import annotations

from typing import Any

import pytest
from pywintypes import com_error

from illusion_forge.cad.tools.advanced import _error_hint
from illusion_forge.cad.vendor.sw_connect import get_com_member, safe_get_com_member


class _NeedsArgsMethod:
    """带参方法标记：动态派发下裸属性访问返回可调用对象本身。"""

    def __init__(self, func: Any) -> None:
        self.func = func


class FakeDynamicCom:
    """模拟 pywin32 dynamic.CDispatch 的派发怪癖。

    无参方法在 ``__getattr__`` 里即被"PROPERTYGET 执行"并返回结果；
    带参方法返回可调用成员本身；未知成员抛 AttributeError。
    """

    def __init__(self, members: dict[str, Any]) -> None:
        self._members = members

    def __getattr__(self, attr: str) -> Any:
        try:
            member = self._members[attr]
        except KeyError:
            raise AttributeError(f"<unknown>.{attr}") from None
        if isinstance(member, _NeedsArgsMethod):
            return member.func
        if callable(member):
            return member()
        return member


# === gcm 二态读取（'str' object is not callable 陷阱） ===


class TestGetComMember:
    def test_no_arg_method_result_returned_without_call(self) -> None:
        """无参方法：裸属性访问已执行，gcm 必须直接返回结果值。"""
        feature = FakeDynamicCom({"GetTypeName2": lambda: "ProfileFeature", "Name": "基准面1"})
        assert get_com_member(feature, "GetTypeName2") == "ProfileFeature"
        assert get_com_member(feature, "Name") == "基准面1"

    def test_args_method_invoked_with_positional_args(self) -> None:
        body = object()
        part = FakeDynamicCom({"GetBodies2": _NeedsArgsMethod(lambda *a: (body,))})
        assert get_com_member(part, "GetBodies2", 0, False) == (body,)

    def test_missing_member_raises_attribute_error(self) -> None:
        feature = FakeDynamicCom({"Name": "草图1"})
        with pytest.raises(AttributeError):
            get_com_member(feature, "GetSpecificFeature2")

    def test_get_typename2_not_typename(self) -> None:
        """成员名打错（TypeName vs GetTypeName2）必须显式抛 AttributeError。"""
        feature = FakeDynamicCom({"GetTypeName2": lambda: "Sketch"})
        with pytest.raises(AttributeError):
            get_com_member(feature, "TypeName2")


# === safe_gcm 的 default 探测契约 ===


class TestSafeGetComMember:
    def test_default_returned_on_missing_member(self) -> None:
        feature = FakeDynamicCom({"Name": "草图1"})
        assert safe_get_com_member(feature, "GetTypeName2", default=None) is None
        assert safe_get_com_member(feature, "GetSpecificFeature2", default="?") == "?"

    def test_default_returned_on_call_failure(self) -> None:
        def boom() -> Any:
            raise com_error(-2147352561, "非选择性的参数。", None, None)

        model = FakeDynamicCom({"GetFeatures": boom})
        assert safe_get_com_member(model, "GetFeatures", default=None) is None

    def test_default_sentinel_preserves_raising_semantics(self) -> None:
        """未传 default 的既有调用方保持 get_com_member 的抛错语义。"""
        feature = FakeDynamicCom({"Name": "草图1"})
        with pytest.raises(AttributeError):
            safe_get_com_member(feature, "GetTypeName2")

    def test_default_none_returns_member_value(self) -> None:
        feature = FakeDynamicCom({"GetTypeName2": lambda: "Sketch"})
        assert safe_get_com_member(feature, "GetTypeName2", default=None) == "Sketch"


# === 错误提示自纠错线索 ===


class TestErrorHint:
    def test_not_callable_hint_names_get_typename2_recipe(self) -> None:
        exc = TypeError("'str' object is not callable")
        hint = _error_hint(exc)
        assert "GetTypeNam" in hint
        assert "无括号" in hint

    def test_attribute_error_hint_names_get_specific_feature2(self) -> None:
        exc = AttributeError("<unknown>.Sketch")
        hint = _error_hint(exc)
        assert "GetSpecificFeature2" in hint
        assert "safe_gcm(obj, '成员名', default=None)" in hint

    def test_paramnotfound_hint_present(self) -> None:
        exc = com_error(-2147352561, "非选择性的参数。", None, None)
        assert "gcm" in _error_hint(exc)
