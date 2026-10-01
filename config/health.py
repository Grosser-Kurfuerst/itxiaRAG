import logging

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def health_live(_request):
    return JsonResponse({"status": "live"})


@require_GET
def health_ready(_request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError as exc:
        logger.warning("readiness failure", extra={
            "event": "database_unavailable", "error_class": type(exc).__name__})
        return JsonResponse({"status": "not_ready"}, status=503)
    logger.info("query not available", extra={"event": "query_not_available"})
    return JsonResponse({"status": "not_ready"}, status=503)
