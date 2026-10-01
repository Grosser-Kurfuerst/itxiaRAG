from django.conf import settings
from contracts.errors import DomainError


def require_available():
    if settings.KB_MAINTENANCE:
        raise DomainError("MAINTENANCE", "服务处于维护窗口", 503, retryable=True)
