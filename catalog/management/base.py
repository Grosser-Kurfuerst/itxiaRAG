from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from rest_framework.exceptions import ValidationError

from contracts.errors import DomainError


class KBCommand(BaseCommand):
    def handle(self, *args, **options):
        try:
            return self.run(*args, **options)
        except DomainError as exc:
            status = 5 if exc.status == 503 else (3 if exc.status == 409 else 2)
            raise CommandError(f"{exc.code}: {exc.message}", returncode=status) from None
        except ValidationError:
            raise CommandError("INVALID_ARGUMENT: 输入字段不符合约定", returncode=2) from None
        except DatabaseError:
            raise CommandError("DEPENDENCY_UNAVAILABLE", returncode=5) from None
        except (OSError, UnicodeError):
            raise CommandError("FILE_ERROR: 无法读取或安全写入文件", returncode=2) from None
