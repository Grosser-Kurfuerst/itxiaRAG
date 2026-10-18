"""检索、推荐请求的 pydantic 基类与校验工具；REST 与 MCP 共用同一份参数定义。"""
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from pydantic_core import PydanticCustomError
from rest_framework.exceptions import ValidationError as DRFValidationError


class RequestModel(BaseModel):
    """拒绝未知字段；显式 null 等同于不传。"""
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def drop_nulls(cls, data):
        if not isinstance(data, dict):
            return data
        return {key: value for key, value in data.items() if value is not None}


def strip_text(value):
    """去掉首尾空白，并拒绝空字节。"""
    if "\x00" in value:
        raise PydanticCustomError("text", "必须是不含空字节的文本")
    return value.strip()


def require_text(value):
    """同 DRF TextField：另外要求能编码为 UTF-8，且去掉首尾空白后非空。"""
    value = strip_text(value)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise PydanticCustomError("text", "必须是合法 UTF-8 文本") from None
    if not value:
        raise PydanticCustomError("text", "文本不能为空")
    return value


def empty_if_null(value):
    return {} if value is None else value


def _error_key(location):
    parts = [str(part) for part in location if part not in {"", "__root__"}]
    return ".".join(parts) or "non_field_errors"


def parse_model(model, data):
    """校验 REST 请求体；失败时转成 DRF ValidationError，由 DRF 默认处理器返回 400。"""
    try:
        return model.model_validate(data)
    except ValidationError as error:
        details = {}
        for item in error.errors():
            details.setdefault(_error_key(item["loc"]), []).append(item["msg"])
        raise DRFValidationError(details) from None
