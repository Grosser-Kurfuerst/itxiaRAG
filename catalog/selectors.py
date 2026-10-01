from django.db.models import F
from catalog.models import ContextUnit, EvidenceUnit, ImportJob
from catalog.policies import require_permission, visible_scopes
from catalog.profiles import active_profiles
from config.runtime import require_available
from contracts.errors import DomainError


def maintenance_job(job_id, actor, permissions=("maintain_source", "review_import")):
    require_permission(actor, *permissions)
    try:
        return (ImportJob.objects.select_related("source")
                .prefetch_related("contexts__children")
                .get(pk=job_id, source__visibility__in=visible_scopes(actor)))
    except ImportJob.DoesNotExist:
        raise DomainError("NOT_FOUND", "对象不存在", 404) from None


def published_contexts(actor, index_profile_hash):
    return ContextUnit.objects.filter(
        build__source__visibility__in=visible_scopes(actor),
        build__source__status="active", build__source__authorization_status="confirmed",
        build__source__current_build_id=F("build_id"),
        build__status="succeeded", build__review_status="approved",
        build__index_profile_hash=index_profile_hash,
    )


def context_detail(context_id, actor):
    require_available()
    config = active_profiles()
    scope = published_contexts(actor, config.index_profile_hash)
    try:
        parent = scope.select_related("build__source").prefetch_related("children").get(pk=context_id)
    except ContextUnit.DoesNotExist:
        raise DomainError("NOT_FOUND", "对象不存在", 404) from None
    if not scope.filter(pk=context_id).exists():
        raise DomainError("NOT_FOUND", "对象不存在", 404)
    return parent


def evidence_detail(evidence_id, actor):
    require_available()
    config = active_profiles()
    scope = published_contexts(actor, config.index_profile_hash)
    try:
        child = (EvidenceUnit.objects.filter(context__in=scope)
                 .select_related("context__build__source").prefetch_related("context__children")
                 .get(pk=evidence_id))
    except EvidenceUnit.DoesNotExist:
        raise DomainError("NOT_FOUND", "对象不存在", 404) from None
    if not scope.filter(pk=child.context_id).exists():
        raise DomainError("NOT_FOUND", "对象不存在", 404)
    return child
