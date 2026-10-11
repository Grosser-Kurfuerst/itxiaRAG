"""来源导入命令的通用部分：清单、试运行、提交与报告；平台命令只负责参数与连接器装配。

命令行由能进入部署环境的维护者执行，不校验账号；HTTP 导入接口仍要求 maintain_source。
"""
from django.core.management.base import CommandError

from catalog.management.base import KBCommand
from config import components
from contracts.errors import SourceAccessError
from ingestion.pipeline import import_processed, preprocess_raw
from sources.importing import SourceImportService, SubmissionResult
from sources.manifest import Manifest, ManifestError, valid_component


class SourceImportCommand(KBCommand):
    source_type: str
    categories: set[str]
    category_pipelines: dict[str, tuple[str, int]]

    def add_source_arguments(self, parser):
        """平台参数，例如语雀的快照目录、公众号的采集目录。"""

    def prepare(self, manifest, options):
        """启动时校验平台配置并返回平台状态；在模型装配之前执行。"""

    def collect(self, state, manifest, options, collections):
        """返回 (connector, refs, read_errors)；collections 是 --only 涉及的集合。"""
        raise NotImplementedError

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        self.add_source_arguments(parser)
        parser.add_argument("--only", action="append", default=[])
        parser.add_argument("--dry-run", action="store_true")

    def run(self, *args, **options):
        try:
            manifest = Manifest.load(options["manifest"], source_type=self.source_type, categories=self.categories)
        except ManifestError as exc:
            raise CommandError(str(exc)) from None
        state = self.prepare(manifest, options)
        dry_run = options["dry_run"]
        only = options["only"]
        for key in only:
            parts = key.split("/")
            if (len(parts) != 2 or any(not valid_component(part) for part in parts)
                    or parts[0] not in manifest.collections):
                raise CommandError(f"--only 必须是清单集合中的集合/条目：{key}")
        # 构造时就校验模型配置；试运行完全不装配模型和保存适配器。
        embedder = None if dry_run else components.embedding_provider()
        registry = components.preprocessors()
        store = None if dry_run else components.document_store()

        def submit(source, raw, schema, version):
            document = preprocess_raw(source, raw, schema, version, registry=registry)
            if dry_run:
                return SubmissionResult(document)
            return SubmissionResult(document, import_processed(source, document, embedder=embedder, store=store))

        collections = [collection for collection in manifest.collections
                       if not only or any(key.startswith(f"{collection}/") for key in only)]
        try:
            connector, refs, read_errors = self.collect(state, manifest, options, collections)
            report = SourceImportService(connector, manifest, self.category_pipelines, submit).run(
                refs, only=only, read_errors=read_errors,
            )
        except SourceAccessError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(report.format())
        if report.summary["failed"]:
            raise CommandError(f"导入结束，{report.summary['failed']} 篇失败，请按报告修正后重跑")
