from catalog.models import ImportJob
from catalog.policies import require_permission, visible_scopes
from contracts.errors import DomainError


def maintenance_job(job_id, actor, permissions=("maintain_source", "review_import")):
    require_permission(actor, *permissions)
    try:
        return (ImportJob.objects.select_related("source")
                .prefetch_related("contexts__children")
                .get(pk=job_id, source__visibility__in=visible_scopes(actor)))
    except ImportJob.DoesNotExist:
        raise DomainError("NOT_FOUND", "对象不存在", 404) from None
