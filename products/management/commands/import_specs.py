import json

from django.core.management.base import CommandError

from catalog.management.base import KBCommand
from products.importing import import_specs


class Command(KBCommand):
    help = "从规格文件导入机型规格；有校验失败时整个文件都不写库"

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def run(self, *args, **options):
        try:
            with open(options["file"], encoding="utf-8") as file:
                records = json.load(file, parse_constant=_reject_constant)
        except (OSError, ValueError) as exc:
            raise CommandError(f"无法读取规格文件：{exc}") from None
        report = import_specs(records, dry_run=options["dry_run"])
        self.stdout.write(report.format())
        if report.failed:
            raise CommandError(f"{len(report.failed)} 条校验失败，整个文件未写库")
        if options["dry_run"]:
            self.stdout.write("试运行，未写库")


def _reject_constant(name):
    raise ValueError(f"不支持 {name}")
