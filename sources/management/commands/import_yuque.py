from django.contrib.auth import get_user_model
from django.core.management.base import CommandError

from catalog.management.base import KBCommand
from catalog.policies import require_permission
from config import components
from ingestion.pipeline import import_processed, preprocess_raw
from sources.yuque.client import YuqueSnapshotClient, valid_component
from sources.yuque.importer import SubmissionResult, YuqueImportService
from sources.yuque.manifest import Manifest, ManifestError


class Command(KBCommand):
    help = "按人工清单导入语雀 Markdown 快照，或只预处理并输出报告"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--snapshot")
        parser.add_argument("--only", action="append", default=[])
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--username")

    def run(self, *args, **options):
        try:
            manifest = Manifest.load(options["manifest"])
        except ManifestError as exc:
            raise CommandError(str(exc)) from None
        if not options["snapshot"]:
            raise CommandError("OpenAPI 读取尚未实现，请提供 --snapshot")
        dry_run = options["dry_run"]
        if not dry_run and not options["username"]:
            raise CommandError("非试运行必须提供 --username")
        only = options["only"]
        for key in only:
            parts = key.split("/")
            if (len(parts) != 2 or any(not valid_component(part) for part in parts)
                    or parts[0] not in manifest.books):
                raise CommandError(f"--only 必须是清单知识库中的知识库/slug：{key}")
        # 构造时就校验模型配置；试运行完全不装配模型和保存适配器。
        embedder = None if dry_run else components.embedding_provider()
        actor = None
        if options["username"]:
            try:
                actor = get_user_model().objects.get(username=options["username"])
            except get_user_model().DoesNotExist:
                raise CommandError("指定账号不存在") from None
            require_permission(actor, "maintain_source")
        registry = components.preprocessors()
        store = None if dry_run else components.document_store()

        def submit(source, raw, schema, version):
            if dry_run:
                document = (registry.process(raw, schema, version) if actor is None else
                            preprocess_raw(source, raw, schema, version, actor, registry=registry))
                return SubmissionResult(document)
            document = preprocess_raw(source, raw, schema, version, actor, registry=registry)
            result = import_processed(source, document, actor, embedder=embedder, store=store)
            return SubmissionResult(document, result)

        client = YuqueSnapshotClient(options["snapshot"])
        books = [book for book in manifest.books if not only or any(key.startswith(f"{book}/") for key in only)]
        refs = [ref for book in books for ref in client.list_docs(book)]
        report = YuqueImportService(client, manifest, components.CATEGORY_PIPELINES, submit).run(refs, only=only)
        self.stdout.write(report.format())
        if report.summary["failed"]:
            raise CommandError(f"导入结束，{report.summary['failed']} 篇失败，请按报告修正后重跑")
