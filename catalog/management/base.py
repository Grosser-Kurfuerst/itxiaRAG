from django.core.management.base import BaseCommand, CommandError

from contracts.errors import DomainError


class KBCommand(BaseCommand):
    def handle(self, *args, **options):
        try:
            return self.run(*args, **options)
        except DomainError as exc:
            raise CommandError(f"{exc.code}: {exc.message}") from None
