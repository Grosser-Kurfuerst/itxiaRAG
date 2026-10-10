from django.core.management.base import CommandError

from config import components
from sources.commands import SourceImportCommand
from sources.manifest import valid_component
from sources.yuque.client import YuqueSnapshotClient, YuqueWebClient
from sources.yuque.connector import CATEGORIES, YuqueConnector, to_doc_ref


class Command(SourceImportCommand):
    help = "按人工清单读取语雀公开网页或 Markdown 快照，导入或只预处理并输出报告"
    source_type = "yuque"
    categories = CATEGORIES
    category_pipelines = components.YUQUE_CATEGORY_PIPELINES

    def add_source_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--snapshot")
        mode.add_argument("--save-snapshot")

    def prepare(self, manifest, options):
        group = manifest.connector.get("group")
        if set(manifest.connector) != {"group"} or not valid_component(group):
            raise CommandError("清单 connector 必须且只能包含非空团队标识 group")
        if options["snapshot"] and options["save_snapshot"]:
            raise CommandError("--snapshot 与 --save-snapshot 互斥")
        return (YuqueSnapshotClient(options["snapshot"]) if options["snapshot"] else
                YuqueWebClient(group))

    def collect(self, client, manifest, options, collections):
        group = manifest.connector["group"]
        # 保存快照覆盖清单内全部已分类文档，不受 --only 限制。
        books = manifest.collections if options["save_snapshot"] else collections
        connector = YuqueConnector(client, group, books)
        refs = connector.list()
        read_errors = None
        if options["save_snapshot"]:
            read_errors = client.save_snapshot(options["save_snapshot"], [
                to_doc_ref(ref) for ref in refs if manifest.classify(ref).category is not None
            ])
            connector = YuqueConnector(YuqueSnapshotClient(options["save_snapshot"]), group, books)
        return connector, refs, read_errors
