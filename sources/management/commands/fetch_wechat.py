from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contracts.errors import DomainError, SourceAccessError
from sources.manifest import Manifest, ManifestError
from sources.wechat.connector import CATEGORIES
from sources.wechat.fetching import fetch_article, listed_articles
from sources.wechat.sogou import SogouWechatClient


class Command(BaseCommand):
    help = "按清单 connector.articles 从搜狗微信搜索下载公众号文章，写成 import_wechat 的采集目录"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--capture", required=True)
        parser.add_argument("--only", action="append", default=[])
        parser.add_argument("--force", action="store_true", help="重新下载已存在的文章")
        parser.add_argument("--interval", type=float, default=3.0, help="请求间隔秒数")

    def handle(self, *args, **options):
        try:
            manifest = Manifest.load(options["manifest"], source_type="wechat", categories=CATEGORIES)
            articles = listed_articles(manifest)
        except ManifestError as exc:
            raise CommandError(str(exc)) from None
        unknown = set(options["only"]) - {article.key for article in articles}
        if unknown:
            raise CommandError(f"--only 不在 connector.articles 中：{', '.join(sorted(unknown))}")
        client = SogouWechatClient(interval=options["interval"])
        failed = 0
        for article in articles:
            if options["only"] and article.key not in options["only"]:
                continue
            try:
                status = fetch_article(client, article, Path(options["capture"]), force=options["force"])
            except SourceAccessError as exc:
                raise CommandError(str(exc)) from None
            except DomainError as exc:
                failed += 1
                status = f"failed  {exc.code}: {exc.message}"
            self.stdout.write(f"{article.key}  {status}")
        if failed:
            raise CommandError(f"下载结束，{failed} 篇失败，请核对清单标题与日期后重跑")
