"""环境配置解析：错误消息仅包含字段名，不打印凭据。"""
import os
import math

from django.core.exceptions import ImproperlyConfigured


def required(name):
    value = os.environ.get(name, "")
    if not value:
        raise ImproperlyConfigured(f"缺少必要环境变量 {name}")
    return value


def boolean(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    if value.lower() not in {"true", "false", "1", "0"}:
        raise ImproperlyConfigured(f"环境变量 {name} 必须为 true/false 或 1/0")
    return value.lower() in {"true", "1"}


def bounded_float(name, default, minimum, maximum=None):
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        result = float(value)
    except ValueError:
        raise ImproperlyConfigured(f"环境变量 {name} 必须为有限数值") from None
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise ImproperlyConfigured(f"环境变量 {name} 超出允许范围")
    return result


def positive_integer(name, default):
    value = os.environ.get(name, "").strip()
    try:
        result = int(value) if value else default
    except ValueError:
        raise ImproperlyConfigured(f"环境变量 {name} 必须为正整数") from None
    if result < 1:
        raise ImproperlyConfigured(f"环境变量 {name} 必须为正整数")
    return result
