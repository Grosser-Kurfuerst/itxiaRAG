from django.core.management.base import CommandError

from config import components
from sources.commands import SourceImportCommand
from sources.manifest import ManifestError
from sources.wechat.connector import CATEGORIES, WechatCaptureConnector
from sources.wechat.fetching import listed_articles


class Command(SourceImportCommand):
    help = "按人工清单读取公众号本地采集目录，导入或只预处理并输出报告"
    source_type = "wechat"
    categories = CATEGORIES
    category_pipelines = components.WECHAT_CATEGORY_PIPELINES

    def add_source_arguments(self, parser):
        parser.add_argument("--capture", required=True)

    def prepare(self, manifest, options):
        # connector 表只供 fetch_wechat 下载；导入时同样校验，避免拼错的配置被静默忽略。
        if manifest.connector:
            try:
                listed_articles(manifest)
            except ManifestError as exc:
                raise CommandError(str(exc)) from None

    def collect(self, state, manifest, options, collections):
        connector = WechatCaptureConnector(options["capture"], collections)
        return connector, connector.list(), None
