import logging

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.models import AnonymousUser

from catalog.profiles import active_profiles
from catalog.models import KnowledgeSource, ImportJob, ContextUnit, EvidenceUnit
from config.components import keyword_backend
from config.runtime import require_available
from contracts.errors import DomainError
from retrieval.keyword import SearchScope

logger = logging.getLogger(__name__)


@require_GET
def health_live(_request):
    return JsonResponse({"status": "live"})


@require_GET
def health_ready(_request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        require_available()
        profiles = active_profiles()
        # 覆盖五张业务表（配置已在上面读取），空库也不能绕过表检查。
        for model in (KnowledgeSource, ImportJob, ContextUnit, EvidenceUnit):
            model.objects.exists()
        keyword_backend().search("readiness", SearchScope(AnonymousUser(), profiles.index_profile_hash), 1)
    except DatabaseError as exc:
        logger.warning("readiness failure", extra={
            "event": "database_unavailable", "error_class": type(exc).__name__})
        return JsonResponse({"status": "not_ready"}, status=503)
    except DomainError as exc:
        logger.warning("readiness failure", extra={"event": "configuration_unavailable", "error_code": exc.code})
        return JsonResponse({"status": "not_ready"}, status=503)
    return JsonResponse({"status": "ready"})
