from contracts.errors import DomainError

PERMISSIONS = {"read_internal", "maintain_source", "review_import", "manage_runtime"}
SYSTEM_USERNAME = "kb-system"


def has_permission(actor, permission):
    return bool(actor.is_authenticated and actor.is_active and actor.has_perm(f"catalog.{permission}"))


def require_permission(actor, *permissions):
    if not any(has_permission(actor, permission) for permission in permissions):
        raise DomainError("PERMISSION_DENIED", "没有该操作权限", 403)


def visible_scopes(actor):
    return ["public", "internal"] if has_permission(actor, "read_internal") else ["public"]
