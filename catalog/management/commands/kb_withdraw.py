from uuid import UUID
from catalog.management.base import KBCommand
from catalog.management.io import actor_by_name
from catalog.services import withdraw_source


class Command(KBCommand):
    help = "幂等撤回来源；保留正文、当前指针和审计"

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, type=UUID)
        parser.add_argument("--actor", required=True)

    def run(self, *args, **options):
        source = withdraw_source(options["source"], actor_by_name(options["actor"]))
        self.stdout.write(f"source_id={source.pk} status={source.status}")
