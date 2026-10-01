import logging
import uuid

from django.core.exceptions import RequestDataTooBig
from django.db import DatabaseError
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response

from contracts.errors import DomainError

logger = logging.getLogger(__name__)


def flatten_fields(value, path=""):
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            result.update(flatten_fields(item, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, list):
        result[path or "non_field_errors"] = [str(item) for item in value]
    else:
        result[path or "non_field_errors"] = [str(value)]
    return result


def exception_handler(exc, context):
    request_id = str(uuid.uuid4())
    fields = {}
    retryable = False
    if isinstance(exc, DomainError):
        code, message, status = exc.code, exc.message, exc.status
        fields, retryable = exc.fields, exc.retryable
    elif isinstance(exc, DatabaseError):
        code, message, status = "DEPENDENCY_UNAVAILABLE", "必要依赖不可用", 503
        retryable = True
    elif isinstance(exc, RequestDataTooBig):
        code, message, status = "INPUT_TOO_LARGE", "请求体超过限制", 413
    elif isinstance(exc, ValidationError):
        code, message, status = "INVALID_ARGUMENT", "请求参数非法", 400
        fields = flatten_fields(exc.detail)
    elif isinstance(exc, APIException):
        status = exc.status_code
        code = {401: "AUTHENTICATION_REQUIRED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND"}.get(status, "INVALID_ARGUMENT")
        message = {401: "请提供有效 Token", 403: "没有该操作权限", 404: "对象不存在"}.get(status, "请求无效")
    else:
        code, message, status = "INTERNAL_ERROR", "服务内部错误", 500
    logger.warning("api_error", extra={"event": "api_error", "request_id": request_id, "error_code": code, "error_class": type(exc).__name__, "status": status})
    response = Response({"request_id": request_id, "error": {
        "code": code, "message": message, "retryable": retryable, "field_errors": fields,
    }}, status=status)
    if getattr(exc, "auth_header", None):
        response["WWW-Authenticate"] = exc.auth_header
    return response
