from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError

from catalog.accounts import configure_account
from catalog.management.base import KBCommand
from contracts.errors import DomainError


class Command(KBCommand):
    help = "部署侧账号及 Token 管理；不会打印密钥或隐式覆盖权限"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--permissions", default=None)
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--token-file")
        group.add_argument("--revoke-token", action="store_true")

    def run(self, *args, **options):
        username = options["username"]
        try:
            UnicodeUsernameValidator()(username)
            if not 1 <= len(username) <= 150:
                raise ValidationError("length")
        except ValidationError:
            raise DomainError("INVALID_ARGUMENT", "账号名格式错误") from None
        raw = options["permissions"]
        permissions = None if raw is None else ([] if raw == "" else raw.split(","))
        user = configure_account(username, permissions, options["token_file"], options["revoke_token"])
        self.stdout.write(f"account_id={user.pk} token_revoked={options['revoke_token']}")
