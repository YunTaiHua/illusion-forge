"""
SolidWorks 外观与材质工具。

SolidWorks 的外观 API 在不同版本和对象类型上差异较多，本模块优先提供
容错封装：同一颜色会依次尝试文档、特征、组件层级的常见接口。
"""
import logging
import re
from typing import Any

from pywintypes import com_error

from .sw_preflight import import_com_dependencies

pythoncom, _win32com, VARIANT = import_com_dependencies()

SW_THIS_CONFIGURATION = 1
SW_SPECIFY_CONFIGURATION = 3


PRESET_COLORS = {
    "iron_red": "#8A0E0E",
    "armor_gold": "#D99A22",
    "dark_gunmetal": "#1F2328",
    "arc_blue": "#2AA8FF",
    "black": "#050505",
    "white": "#F2F2F2",
    "silver": "#BFC4C8",
    "aqua_blue": "#4FA6A8",
    "glass_tint": "#10232E",
    "signal_red": "#E31B35",
    "light_cyan": "#9DEBFF",
    "tire_black": "#111315",
    "graphite": "#33383D",
}


def rgb01(color: Any) -> Any:
    """
    将颜色转换为 0..1 RGB。

    支持:
        - 预设名，如 "iron_red"
        - 十六进制，如 "#8A0E0E"
        - 0..255 RGB 元组
        - 0..1 RGB 元组
    """
    if isinstance(color, str):
        value = PRESET_COLORS.get(color, color).strip()
        match = re.fullmatch(r"#?([0-9a-fA-F]{6})", value)
        if not match:
            raise ValueError(f"未知颜色: {color}")
        hex_value = match.group(1)
        return tuple(int(hex_value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    if len(color) != 3:
        raise ValueError("RGB 颜色必须包含 3 个值")
    if max(color) > 1:
        return tuple(float(v) / 255.0 for v in color)
    return tuple(float(v) for v in color)


def material_values(color: Any, ambient: float = 0.35, diffuse: float = 0.75,
                    specular: float = 0.45, shininess: float = 0.35,
                    transparency: float = 0.0, emission: float = 0.0) -> Any:
    """
    生成 SolidWorks 材质属性数组。

    数组顺序为:
        red, green, blue, ambient, diffuse, specular, shininess, transparency, emission
    """
    red, green, blue = rgb01(color)
    return [red, green, blue, ambient, diffuse, specular, shininess, transparency, emission]


def material_variant(values: Any) -> Any:
    """把九位材质数组封装为 COM SAFEARRAY(double)，防止 RGB 通道错位。"""
    if len(values) != 9:
        raise ValueError("SolidWorks 材质数组必须包含 9 个值")
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(v) for v in values])


def _configuration_args(configuration: Any) -> Any:
    """生成 SetMaterialPropertyValues2 的配置选项和名称参数。"""
    if not configuration:
        return SW_THIS_CONFIGURATION, None
    names = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [str(configuration)])
    return SW_SPECIFY_CONFIGURATION, names


def _try_set(target: Any, attr_name: str, values: Any, *args: Any) -> bool:
    """尝试设置属性或调用方法；void 方法无异常即视为成功。"""
    try:
        member = getattr(target, attr_name)
        if callable(member):
            result = member(values, *args)
        else:
            setattr(target, attr_name, values)
            result = True
        return bool(result) if result is not None else True
    except (com_error, AttributeError, TypeError, ValueError, OSError, KeyError, IndexError):
        return False


def get_material_property_values(target: Any) -> Any:
    """读取文档、特征或组件的九位材质数组，读取失败返回 None。"""
    readers: list[Any] = [
        lambda: target.MaterialPropertyValues,
        lambda: target.GetMaterialPropertyValues(),
    ]
    for reader in readers:
        try:
            values = reader()
            if values is not None and len(values) >= 9:
                return tuple(float(value) for value in values[:9])
        except (com_error, AttributeError, TypeError, ValueError, OSError, KeyError, IndexError):
            logging.getLogger(__name__).debug('vendor COM 边界探测失败', exc_info=True)
    return None


def verify_appearance(target: Any, color: Any, tolerance: float=0.01) -> Any:
    """回读并验证目标前三位 RGB，返回结构化结果。"""
    expected = rgb01(color)
    actual_values = get_material_property_values(target)
    actual = actual_values[:3] if actual_values else None
    max_error = max(abs(a - e) for a, e in zip(actual, expected)) if actual is not None else None
    return {
        "ok": actual is not None and max_error is not None and max_error <= float(tolerance),
        "expected_rgb": expected,
        "actual_rgb": actual,
        "max_error": max_error,
    }


def set_document_appearance(model: Any, color: Any, configuration: Any="") -> Any:
    """
    设置文档级外观颜色。

    返回:
        bool 是否至少一个接口调用成功。
    """
    packed = material_variant(material_values(color))
    option, names = _configuration_args(configuration)
    if configuration:
        extension = getattr(model, "Extension", None)
        wrote = bool(extension) and _try_set(
            extension, "SetMaterialPropertyValues", packed, option, names
        )
    else:
        wrote = _try_set(model, "MaterialPropertyValues", packed)
    return wrote and verify_appearance(model, color)["ok"]


def set_feature_appearance(feature: Any, color: Any, configuration: Any="") -> Any:
    """
    设置特征级外观颜色。

    返回:
        bool 是否至少一个接口调用成功。
    """
    packed = material_variant(material_values(color))
    option, names = _configuration_args(configuration)
    wrote = _try_set(feature, "SetMaterialPropertyValues2", packed, option, names)
    if not wrote and not configuration:
        wrote = _try_set(feature, "SetMaterialPropertyValues", packed)
    return wrote and verify_appearance(feature, color)["ok"]


def set_component_appearance(component: Any, color: Any, configuration: Any="") -> Any:
    """
    设置装配体组件外观颜色。

    返回:
        bool 是否至少一个接口调用成功。
    """
    packed = material_variant(material_values(color))
    option, names = _configuration_args(configuration)
    wrote = _try_set(component, "SetMaterialPropertyValues2", packed, option, names)
    if not wrote and not configuration:
        wrote = _try_set(component, "MaterialPropertyValues", packed)
    return wrote and verify_appearance(component, color)["ok"]


def apply_component_palette(assignments: Any, strict: bool=True) -> Any:
    """
    批量设置组件颜色并逐项回读。

    参数:
        assignments: ``[(component, color), ...]``
        strict: True 时任何组件失败立即抛出 RuntimeError

    返回:
        list[dict]，包含 index、color、ok、expected_rgb、actual_rgb、max_error
    """
    reports = []
    for index, (component, color) in enumerate(assignments):
        wrote = set_component_appearance(component, color)
        report = verify_appearance(component, color)
        report.update({"index": index, "color": color, "ok": wrote and report["ok"]})
        reports.append(report)
        if strict and not report["ok"]:
            raise RuntimeError(
                f"组件 {index} 外观验证失败: 预期 {report['expected_rgb']}，"
                f"实际 {report['actual_rgb']}"
            )
    return reports


def apply_named_appearance(target: Any, name: Any) -> Any:
    """
    给任意常见对象应用预设外观。

    该函数会按文档、组件、特征的顺序尝试。
    """
    return (
        set_document_appearance(target, name)
        or set_component_appearance(target, name)
        or set_feature_appearance(target, name)
    )
