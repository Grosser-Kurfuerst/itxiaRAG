from django.core.management.base import CommandError

from config import components
from sources.commands import SourceImportCommand
from sources.wechat.connector import CATEGORIES, WechatCaptureConnector


class Command(SourceImportCommand):
    help = "按人工清单读取公众号本地采集目录，导入或只预处理并输出报告"
    source_type = "wechat"
    categories = CATEGORIES
    category_pipelines = components.WECHAT_CATEGORY_PIPELINES

    def add_source_arguments(self, parser):
        parser.add_argument("--capture", required=True)

    def prepare(self, manifest, options):
        if manifest.connector:
            raise CommandError("公众号清单不使用 connector 参数")

    def collect(self, state, manifest, options, collections):
        connector = WechatCaptureConnector(options["capture"], collections)
        return connector, connector.list(), None
