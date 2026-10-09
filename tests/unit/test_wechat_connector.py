from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from contracts.errors import DomainError
from sources.wechat.connector import WechatCaptureConnector, article_identity
from tests.wechat_capture import PERMANENT, REVIEW_HTML, build_capture, write


@pytest.fixture
def capture(tmp_path):
    return build_capture(tmp_path)


@pytest.mark.parametrize("url,expected", [
    (PERMANENT, ("mp:MzA5MDAwMDAwMA==:2650000001:2",
                 "https://mp.weixin.qq.com/s?__biz=MzA5MDAwMDAwMA%3D%3D&mid=2650000001&idx=2&sn=abc123")),
    ("http://mp.weixin.qq.com/s?__biz=MzA5&mid=1&idx=1", ("mp:MzA5:1:1", "https://mp.weixin.qq.com/s?__biz=MzA5&mid=1&idx=1")),
    ("https://mp.weixin.qq.com/s?__biz=MzA5&amp;mid=1&amp;idx=1", ("mp:MzA5:1:1", "https://mp.weixin.qq.com/s?__biz=MzA5&mid=1&idx=1")),
    ("https://mp.weixin.qq.com/s/AbC-123_x?scene=1", ("mp:s:AbC-123_x", "https://mp.weixin.qq.com/s/AbC-123_x")),
    (None, ("wechat-capture:lab/item", None)),
])
def test_article_identity_uses_permanent_links_and_falls_back_to_capture_key(url, expected):
    assert article_identity(url, "lab/item") == expected


@pytest.mark.parametrize("url", [
    "https://mp.weixin.qq.com/s?src=11&timestamp=1&ver=1&signature=x",
    "https://mp.weixin.qq.com/s?__biz=MzA5&mid=abc&idx=1",
    "https://example.com/s/AbC",
    "",
])
def test_temporary_or_unrecognized_links_are_rejected_instead_of_silently_degrading(url):
    with pytest.raises(DomainError, match="不是公众号永久链接或短链接") as error:
        article_identity(url, "lab/item")
    assert error.value.code == "INVALID_CAPTURE"


def test_list_reads_sidecars_in_order_and_fetch_returns_html_with_platform_metadata(capture):
    root, _ = capture
    connector = WechatCaptureConnector(root, ["synthetic-lab"])
    refs = connector.list()
    assert [ref.key for ref in refs] == [
        "synthetic-lab/2026-09-28-review", "synthetic-lab/2026-09-30-guide",
        "synthetic-lab/2026-10-01-reprint", "synthetic-lab/2026-10-02-new",
    ]
    assert refs == connector.list()
    review = connector.fetch(refs[0])
    assert review.ref.collection == "synthetic-lab" and review.ref.collection_path == ()
    assert review.ref.canonical_locator == "mp:MzA5MDAwMDAwMA==:2650000001:2"
    assert review.source_url.endswith("&sn=abc123")
    assert review.raw.content == REVIEW_HTML.encode() and review.raw.media_type == "text/html"
    assert review.raw.metadata == {"title": "合成评测：笔记本 A", "source_date": "2026-09-28",
                                   "wechat": {"account": "合成评测室", "author": "合成作者"}}
    reprint = connector.fetch(refs[2])
    assert reprint.ref.canonical_locator == "wechat-capture:synthetic-lab/2026-10-01-reprint"
    assert reprint.source_url is None
    assert reprint.raw.metadata == {"title": "合成转载评测", "wechat": {"account": "synthetic-lab"}}


@pytest.mark.parametrize("sidecar,message", [
    (None, "缺少旁注"),
    ("{", "缺少旁注"),
    ("[]", "必须是对象"),
    ('{"title": "合成", "tags": []}', "字段限于"),
    ('{"title": " "}', "缺少标题"),
    ('{"title": "合成", "author": 1}', "必须是文本"),
    ('{"title": "合成", "date": "2026/09/28"}', "YYYY-MM-DD"),
    ('{"title": "合成", "date": "20260928"}', "YYYY-MM-DD"),
    ('{"title": "合成", "url": "https://mp.weixin.qq.com/s?src=11&signature=x"}', "永久链接"),
])
def test_invalid_sidecar_fails_listing_with_clear_error(tmp_path, sidecar, message):
    directory = tmp_path / "lab"
    directory.mkdir()
    (directory / "item.html").write_text("<p>合成</p>", encoding="utf-8")
    if sidecar is not None:
        (directory / "item.json").write_text(sidecar, encoding="utf-8")
    with pytest.raises(DomainError, match=message) as error:
        WechatCaptureConnector(tmp_path, ["lab"]).list()
    assert error.value.code == "INVALID_CAPTURE"


def test_same_article_captured_twice_fails_listing(capture):
    root, _ = capture
    write(root / "synthetic-lab", "2026-10-03-copy", REVIEW_HTML, title="重复采集",
          url=PERMANENT.replace("&scene=21", "&scene=126"))
    with pytest.raises(DomainError, match="2026-10-03-copy 与 synthetic-lab/2026-09-28-review 是同一篇文章"):
        WechatCaptureConnector(root, ["synthetic-lab"]).list()


def test_missing_account_directory_fails_listing_and_missing_page_fails_one_fetch(capture):
    root, _ = capture
    with pytest.raises(DomainError, match="缺少账号目录"):
        WechatCaptureConnector(root, ["missing"]).list()
    connector = WechatCaptureConnector(root, ["synthetic-lab"])
    ref = connector.list()[0]
    (root / "synthetic-lab/2026-09-28-review.html").unlink()
    with pytest.raises(DomainError) as error:
        connector.fetch(ref)
    assert error.value.code == "CAPTURE_READ_FAILED"


def test_command_dry_run_uses_manifest_metadata_and_needs_no_account_or_models(capture):
    root, manifest = capture
    output = StringIO()
    with patch("config.components.embedding_provider") as embedder, \
            patch("config.components.document_store") as store, \
            patch("sources.commands.get_user_model") as users:
        call_command("import_wechat", manifest=str(manifest), capture=str(root), dry_run=True, stdout=output)
    embedder.assert_not_called()
    store.assert_not_called()
    users.assert_not_called()
    text = output.getvalue()
    assert "product_review(manifest)" in text and "purchase_guide(manifest)" in text
    assert "reprint" in text and "请在清单中登记类别或 skip" in text
    assert "preprocessed=2 skipped=1 unregistered=1 failed=0" in text
    assert "续航约 9 小时" not in text


def test_command_review_without_entity_title_is_a_per_document_failure(capture):
    root, manifest = capture
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(
        'metadata = { entity_title = "合成笔记本 A" }\n', ""), encoding="utf-8")
    output = StringIO()
    with pytest.raises(CommandError, match="1 篇失败"):
        call_command("import_wechat", manifest=str(manifest), capture=str(root), dry_run=True, stdout=output)
    assert "ENTITY_TITLE_REQUIRED" in output.getvalue() and "preprocessed=1" in output.getvalue()


@pytest.mark.parametrize("change,message", [
    (("source_type = \"wechat\"", "source_type = \"yuque\""), "source_type"),
    (("source_type = \"wechat\"\n", "source_type = \"wechat\"\n[connector]\ngroup = \"x\"\n"), "connector"),
    (("category = \"purchase_guide\"", "category = \"tutorial\""), "category"),
])
def test_command_rejects_wrong_manifest_before_listing(capture, change, message):
    root, manifest = capture
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(*change), encoding="utf-8")
    with patch.object(WechatCaptureConnector, "list") as listing:
        with pytest.raises(CommandError, match=message):
            call_command("import_wechat", manifest=str(manifest), capture=str(root), dry_run=True)
    listing.assert_not_called()


def test_command_missing_capture_directory_fails_whole_batch(capture, tmp_path):
    _, manifest = capture
    with pytest.raises(CommandError, match="INVALID_CAPTURE"):
        call_command("import_wechat", manifest=str(manifest), capture=str(tmp_path / "missing"), dry_run=True)
