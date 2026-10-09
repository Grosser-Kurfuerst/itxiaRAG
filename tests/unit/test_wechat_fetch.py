import json
import tomllib
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from contracts.errors import DomainError, SourceAccessError
from sources.manifest import Manifest, ManifestError
from sources.wechat.connector import CATEGORIES, WechatCaptureConnector
from sources.wechat.fetching import fetch_article, listed_articles
from sources.wechat.sogou import SearchHit, SogouBlockedError, SogouWechatClient
from tests.wechat_capture import ARTICLE_PAGE, FETCH_MANIFEST, JUMP_PAGE, SEARCH_PAGE


class FakeResponse:
    def __init__(self, url, body):
        self.url, self.body = url, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def geturl(self):
        return self.url

    def read(self):
        return self.body.encode("utf-8")


class FakeOpener:
    """按网址前缀返回合成页面，记录请求，代替网络。"""

    def __init__(self, pages):
        self.pages, self.requests = pages, []

    def open(self, request, timeout):
        self.requests.append(request)
        url = request.full_url
        body = next(body for prefix, body in self.pages.items() if url.startswith(prefix))
        return FakeResponse(url, body)


PAGES = {
    "https://weixin.sogou.com/weixin?": SEARCH_PAGE,
    "https://weixin.sogou.com/link?": JUMP_PAGE,
    "https://weixin.sogou.com/": "<html>首页</html>",
    "https://mp.weixin.qq.com/s?src=11": ARTICLE_PAGE,
}


def client(pages=PAGES):
    opener = FakeOpener(pages)
    return SogouWechatClient(interval=0, opener=opener), opener


def _load(text):
    return Manifest(tomllib.loads(text), source_type="wechat", categories=CATEGORIES)


def test_search_parses_title_account_date_and_link_after_visiting_home_page():
    sogou, opener = client()
    hits = sogou.search("合成评测：笔记本 A")
    assert opener.requests[0].full_url == "https://weixin.sogou.com/"
    assert hits[0] == SearchHit("合成评测:笔记本 A", "合成评测室", "2026-09-28", "/link?url=AAA&query=合成%20评测")
    assert [(hit.account, hit.date) for hit in hits[1:]] == [("合成评测室", "2023-11-15"), ("转载号", None)]


def test_download_follows_jump_pieces_and_keeps_only_page_identity_and_content():
    sogou, opener = client()
    hit = sogou.search("合成")[0]
    article = sogou.download(hit)
    jump, page = opener.requests[-2:]
    assert jump.headers["Referer"].startswith("https://weixin.sogou.com/weixin?")
    assert page.full_url == "https://mp.weixin.qq.com/s?src=11&signature=x"
    assert article.url == "https://mp.weixin.qq.com/s?__biz=MzA5MDAwMDAwMA%3D%3D&mid=2650000001&idx=2"
    assert (article.account, article.date) == ("合成评测室", "2026-09-28")
    assert "<script" not in article.html and "<style" not in article.html and "续航约 9 小时" in article.html


def test_captcha_stops_whole_batch_and_unknown_jump_page_fails_one_article():
    blocked, _ = client({**PAGES, "https://weixin.sogou.com/weixin?": "<script src=antispider.js>"})
    with pytest.raises(SogouBlockedError) as error:
        blocked.search("合成")
    assert isinstance(error.value, SourceAccessError)
    broken, _ = client({**PAGES, "https://weixin.sogou.com/link?": "<html>改版</html>"})
    with pytest.raises(DomainError) as error:
        broken.download(broken.search("合成")[0])
    assert error.value.code == "WECHAT_PARSE_FAILED"


def test_fetch_writes_capture_that_import_connector_reads(tmp_path):
    article = listed_articles(_load(FETCH_MANIFEST))[0]
    sogou, _ = client()
    assert fetch_article(sogou, article, tmp_path) == "downloaded"
    sidecar = json.loads((tmp_path / "synthetic-lab/2026-09-28-review.json").read_text(encoding="utf-8"))
    assert sidecar == {"title": "合成评测：笔记本 A", "date": "2026-09-28", "account": "合成评测室",
                       "url": "https://mp.weixin.qq.com/s?__biz=MzA5MDAwMDAwMA%3D%3D&mid=2650000001&idx=2"}
    ref = WechatCaptureConnector(tmp_path, ["synthetic-lab"]).list()[0]
    assert ref.canonical_locator == "mp:MzA5MDAwMDAwMA==:2650000001:2"
    with patch.object(sogou, "search") as search:
        assert fetch_article(sogou, article, tmp_path) == "exists"
    search.assert_not_called()


@pytest.mark.parametrize("change,problem", [
    (('date = "2026-09-28"', 'date = "2026-09-29"'), "未找到"),
    (('= "合成评测室"', '= "其他评测室"'), "未找到"),
])
def test_article_must_match_account_title_and_date(tmp_path, change, problem):
    article = listed_articles(_load(FETCH_MANIFEST.replace(*change)))[0]
    with pytest.raises(DomainError, match=problem) as error:
        fetch_article(client()[0], article, tmp_path)
    assert error.value.code == "WECHAT_NOT_FOUND"
    assert not (tmp_path / "synthetic-lab").exists()


def test_several_matching_articles_are_not_guessed(tmp_path):
    article = listed_articles(_load(FETCH_MANIFEST))[0]
    hit = SearchHit("合成评测：笔记本 A", "合成评测室", None, "/link?url=X")
    sogou = client()[0]
    with patch.object(sogou, "search", return_value=[hit, hit]):
        with pytest.raises(DomainError, match="找到 2 篇"):
            fetch_article(sogou, article, tmp_path)


@pytest.mark.parametrize("change,message", [
    (("[connector.accounts]\nsynthetic-lab", "[connector.accounts]\nother"), "connector.accounts.other"),
    (('date = "2026-09-28" }', 'date = "2026-9-28" }'), "YYYY-MM-DD"),
    (('title = "合成评测：笔记本 A", ', ""), "title 与 date"),
    (('"synthetic-lab/2026-09-28-review" = {', '"synthetic-lab/unlisted" = {'), "docs"),
])
def test_invalid_download_list_is_rejected(change, message):
    with pytest.raises(ManifestError, match=message):
        listed_articles(_load(FETCH_MANIFEST.replace(*change)))


def test_repository_manifest_is_a_valid_download_list():
    listed = listed_articles(Manifest.load("sources/wechat/manifests/bibar.toml", source_type="wechat",
                                           categories=CATEGORIES))
    assert listed and all(article.account == "笔吧评测室" for article in listed)


def test_command_fetches_then_import_dry_run_reads_same_manifest(tmp_path):
    path = tmp_path / "manifest.toml"
    path.write_text(FETCH_MANIFEST, encoding="utf-8")
    capture = tmp_path / "capture"
    output = StringIO()
    with patch("sources.management.commands.fetch_wechat.SogouWechatClient",
               side_effect=lambda **kwargs: client()[0]):
        call_command("fetch_wechat", manifest=str(path), capture=str(capture), stdout=output)
    assert "synthetic-lab/2026-09-28-review  downloaded" in output.getvalue()
    output = StringIO()
    call_command("import_wechat", manifest=str(path), capture=str(capture), dry_run=True, stdout=output)
    assert "preprocessed=1" in output.getvalue()


def test_command_reports_per_article_failure_and_stops_on_captcha(tmp_path):
    path = tmp_path / "manifest.toml"
    path.write_text(FETCH_MANIFEST.replace('date = "2026-09-28" }', 'date = "2026-09-29" }'), encoding="utf-8")
    output = StringIO()
    with patch("sources.management.commands.fetch_wechat.SogouWechatClient",
               side_effect=lambda **kwargs: client()[0]):
        with pytest.raises(CommandError, match="1 篇失败"):
            call_command("fetch_wechat", manifest=str(path), capture=str(tmp_path), stdout=output)
    assert "WECHAT_NOT_FOUND" in output.getvalue()
    blocked = client({**PAGES, "https://weixin.sogou.com/weixin?": "antispider"})[0]
    with patch("sources.management.commands.fetch_wechat.SogouWechatClient", return_value=blocked):
        with pytest.raises(CommandError, match="验证码"):
            call_command("fetch_wechat", manifest=str(path), capture=str(tmp_path))
