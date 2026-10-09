"""按清单 connector 表的文章列表从搜狗下载网页，写成 WechatCaptureConnector 读取的采集目录。

只有账号、标题（统一全角半角后）与发布日期都一致才算找到；找不到或多篇一致都按单篇失败报告，不猜测。
"""
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from contracts.errors import DomainError
from sources.manifest import Manifest, ManifestError
from sources.wechat.sogou import SogouWechatClient


@dataclass(frozen=True)
class ListedArticle:
    key: str
    account: str
    title: str
    date: str


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def listed_articles(manifest: Manifest) -> list[ListedArticle]:
    connector = manifest.connector
    accounts, articles = connector.get("accounts"), connector.get("articles")
    if set(connector) != {"accounts", "articles"} or not isinstance(accounts, dict) or not isinstance(articles, dict):
        raise ManifestError("下载需要 connector.accounts（集合 → 公众号名）与 connector.articles（集合/条目 → 标题与日期）")
    for collection, name in accounts.items():
        if collection not in manifest.collections or not _text(name):
            raise ManifestError(f"connector.accounts.{collection} 必须是已登记集合的公众号名")
    listed = []
    for key, entry in articles.items():
        collection, _, item = key.partition("/")
        if collection not in accounts or not item or "/" in item or key not in manifest.docs:
            raise ManifestError(f"connector.articles.{key} 必须对应 docs 中已登记账号的条目")
        if not isinstance(entry, dict) or set(entry) != {"title", "date"} or not _text(entry["title"]):
            raise ManifestError(f"connector.articles.{key} 必须且只能包含 title 与 date")
        try:
            if not isinstance(entry["date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["date"]):
                raise ValueError
            date.fromisoformat(entry["date"])
        except ValueError:
            raise ManifestError(f"connector.articles.{key}.date 必须是 YYYY-MM-DD 文本") from None
        listed.append(ListedArticle(key, accounts[collection], entry["title"].strip(), entry["date"]))
    return listed


def _same_title(left: str, right: str) -> bool:
    # 搜狗会把全角标点显示为半角，例如“！”变成“!”。
    def normal(text):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    return normal(left) == normal(right)


def fetch_article(client: SogouWechatClient, article: ListedArticle, root: Path, *, force=False) -> str:
    """返回 downloaded 或 exists；单篇问题抛 DomainError，验证码抛 SourceAccessError。"""
    page = root / f"{article.key}.html"
    if page.exists() and not force:
        return "exists"
    hits = [hit for hit in client.search(article.title)
            if hit.account == article.account and _same_title(hit.title, article.title)
            and hit.date in (None, article.date)]
    if len(hits) != 1:
        problem = "未找到" if not hits else f"找到 {len(hits)} 篇"
        raise DomainError("WECHAT_NOT_FOUND", f"{problem}账号、标题与日期一致的文章")
    downloaded = client.download(hits[0])
    if downloaded.account != article.account or downloaded.date != article.date:
        raise DomainError("WECHAT_NOT_FOUND", f"下载结果为 {downloaded.account} {downloaded.date}，与清单不一致")
    page.parent.mkdir(parents=True, exist_ok=True)
    sidecar = {"title": article.title, "url": downloaded.url, "date": downloaded.date, "account": downloaded.account}
    page.with_suffix(".json").write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")
    # 最后写网页：中途失败时没有 .html，重跑会重新下载。
    page.write_text(downloaded.html, encoding="utf-8")
    return "downloaded"
