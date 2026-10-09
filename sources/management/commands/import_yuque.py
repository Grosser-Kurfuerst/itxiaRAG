from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.management.base import CommandError

from catalog.management.base import KBCommand
from catalog.policies import require_permission
from config import components
from ingestion.pipeline import import_processed, preprocess_raw
from sources.yuque.client import YuqueAuthenticationError, YuqueOpenApiClient, YuqueSnapshotClient, valid_component
from sources.yuque.importer import SubmissionResult, YuqueImportService
from sources.yuque.manifest import Manifest, ManifestError


class Command(KBCommand):
    help = "按人工清单读取语雀 OpenAPI 或 Markdown 快照，导入或只预处理并输出报告"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--snapshot")
        mode.add_argument("--save-snapshot")
        parser.add_argument("--only", action="append", default=[])
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--username")

    def run(self, *args, **options):
        try:
            manifest = Manifest.load(options["manifest"])
        except ManifestError as exc:
            raise CommandError(str(exc)) from None
        if options["snapshot"] and options["save_snapshot"]:
            raise CommandError("--snapshot 与 --save-snapshot 互斥")
        client = (YuqueSnapshotClient(options["snapshot"]) if options["snapshot"] else
                  YuqueOpenApiClient(settings.YUQUE_API_BASE, settings.YUQUE_TOKEN, manifest.group))
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

        books = [book for book in manifest.books if options["save_snapshot"] or not only
                 or any(key.startswith(f"{book}/") for key in only)]
        try:
            refs = [ref for book in books for ref in client.list_docs(book)]
            read_errors = None
            if options["save_snapshot"]:
                read_errors = client.save_snapshot(options["save_snapshot"],
                                                   [ref for ref in refs if manifest.classify(ref).category is not None])
                client = YuqueSnapshotClient(options["save_snapshot"])
            report = YuqueImportService(client, manifest, components.CATEGORY_PIPELINES, submit).run(
                refs, only=only, read_errors=read_errors,
            )
        except YuqueAuthenticationError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(report.format())
        if report.summary["failed"]:
            raise CommandError(f"导入结束，{report.summary['failed']} 篇失败，请按报告修正后重跑")
