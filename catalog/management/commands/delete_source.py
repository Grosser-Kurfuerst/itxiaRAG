from django.core.management.base import CommandError
from django.db.models import Count

from catalog.management.base import KBCommand
from catalog.models import KnowledgeSource


class Command(KBCommand):
    help = "按来源类型和定位符删除来源及其父段、子块；先用 --dry-run 核对"

    def add_arguments(self, parser):
        parser.add_argument("--source-type", required=True)
        parser.add_argument("--locator", action="append", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def run(self, *args, **options):
        locators = set(options["locator"])
        sources = list(KnowledgeSource.objects
                       .filter(source_type=options["source_type"], canonical_locator__in=locators)
                       .annotate(parents=Count("contexts", distinct=True), children=Count("contexts__children"))
                       .order_by("canonical_locator"))
        missing = locators - {source.canonical_locator for source in sources}
        if missing:
            raise CommandError(f"库中没有这些来源：{', '.join(sorted(missing))}")
        for source in sources:
            self.stdout.write(f"{source.canonical_locator}  {source.title}  "
                              f"parents={source.parents} children={source.children}")
        if options["dry_run"]:
            return
        # 父段、子块随外键级联删除，QuerySet.delete() 在一个事务内完成。
        KnowledgeSource.objects.filter(pk__in=[source.pk for source in sources]).delete()
        self.stdout.write(f"deleted={len(sources)}")
