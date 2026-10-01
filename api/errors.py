import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from contracts.errors import DomainError

logger = logging.getLogger(__name__)


def exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.status)
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response
    # 不为数据库故障增加恢复状态机；失败明确返回 500，不冒充无结果。
    logger.error("request_failed error_class=%s", type(exc).__name__)
    return Response({"error": {"code": "INTERNAL_ERROR", "message": "服务内部错误"}}, status=500)
