import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction
from rest_framework.authtoken.models import Token

from catalog.policies import PERMISSIONS
from contracts.errors import DomainError


def permissions_for(names):
    if not set(names) <= PERMISSIONS:
        raise DomainError("INVALID_ARGUMENT", "权限名称无效")
    permissions = list(Permission.objects.filter(content_type__app_label="catalog", codename__in=names))
    if len(permissions) != len(set(names)):
        raise DomainError("INITIALIZATION_REQUIRED", "请先运行数据库迁移", 503)
    return permissions


def write_token_file(path, key):
    """新文件独占创建；重跑只接受相同 Token，不跟随符号链接。"""
    path = Path(path)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            if stream.read(128).strip() != key:
                raise DomainError("TOKEN_FILE_CONFLICT", "目标文件已存在且内容不同")
            os.fchmod(stream.fileno(), 0o600)
        return
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(key + "\n")


@transaction.atomic
def configure_account(username, permission_names=None, token_file=None, revoke=False):
    if not username:
        raise DomainError("INVALID_ARGUMENT", "该账号名不允许用于账号发放")
    permissions = permissions_for(permission_names or [])
    user, created = get_user_model().objects.get_or_create(username=username)
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
        user.user_permissions.set(permissions)
    elif permission_names is not None:
        existing = set(user.user_permissions.filter(content_type__app_label="catalog").values_list("codename", flat=True))
        if existing != set(permission_names):
            raise DomainError("ACCOUNT_PERMISSION_CONFLICT", "已有账号权限不同，不能隐式覆盖")
    if token_file:
        if not user.is_active:
            raise DomainError("INVALID_ARGUMENT", "停用账号不能发放 Token")
        token, _ = Token.objects.get_or_create(user=user)
        write_token_file(token_file, token.key)
    elif revoke:
        Token.objects.filter(user=user).delete()
    return user
