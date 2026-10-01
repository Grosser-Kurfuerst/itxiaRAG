"""环境配置解析：错误消息仅包含字段名，不打印凭据。"""
import os

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
