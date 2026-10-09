import json
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from contracts.errors import DomainError
from sources.wechat.connector import WechatCaptureConnector, article_identity


REVIEW_HTML = ('<html><body><div id="js_content"><h2>合成笔记本 A</h2><p><strong>配置</strong></p><p>16GB 内存。</p>'
               '<p><strong>续航</strong></p><p>续航约 9 小时。</p></div></body></html>')
GUIDE_HTML = ('<div id="js_content"><h1>合成选购指南</h1><h2>6000元</h2><h3>合成笔记本 A</h3><p>续航好。</p>'
              '<h3>合成笔记本 B</h3><p>游戏快。</p></div>')
PERMANENT = "https://mp.weixin.qq.com/s?__biz=MzA5MDAwMDAwMA==&mid=2650000001&idx=2&sn=abc123&chksm=x&scene=21"


def write(directory, name, html, **sidecar):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.html").write_text(html, encoding="utf-8")
    (directory / f"{name}.json").write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def capture(tmp_path):
    root = tmp_path / "capture"
    account = root / "synthetic-lab"
    write(account, "2026-09-28-review", REVIEW_HTML, title="合成评测：笔记本 A", url=PERMANENT,
          date="2026-09-28", author="合成作者", account="合成评测室")
    write(account, "2026-09-30-guide", GUIDE_HTML, title="合成选购指南",
          url="https://mp.weixin.qq.com/s/AbC-123_x")
    write(account, "2026-10-01-reprint", "<p>合成转载</p>", title="合成转载评测")
    write(account, "2026-10-02-new", "<p>合成新文章</p>", title="未登记文章")
    manifest = tmp_path / "manifest.toml"
    manifest.write_text('''version = 2
source_type = "wechat"
[collections.synthetic-lab]
visibility = "internal"
[docs."synthetic-lab/2026-09-28-review"]
category = "product_review"
metadata = { entity_title = "合成笔记本 A" }
[docs."synthetic-lab/2026-09-30-guide"]
category = "purchase_guide"
visibility = "public"
[docs."synthetic-lab/2026-10-01-reprint"]
skip = "reprint"
''', encoding="utf-8")
    return root, manifest


@pytest.mark.parametrize("url,expected", [
    (PERMANENT, ("mp:MzA5MDAwMDAwMA==:2650000001:2",
                 "https://mp.weixin.qq.com/s?__biz=MzA5MDAwMDAwMA%3D%3D&mid=2650000001&idx=2&sn=abc123")),
    ("http://mp.weixin.qq.com/s?__biz=MzA5&mid=1&idx=1", ("mp:MzA5:1:1", "https://mp.weixin.qq.com/s?__biz=MzA5&mid=1&idx=1")),
    ("https://mp.weixin.qq.com/s/AbC-123_x?scene=1", ("mp:s:AbC-123_x", "https://mp.weixin.qq.com/s/AbC-123_x")),
    ("https://mp.weixin.qq.com/s?src=11&timestamp=1&ver=1&signature=x", ("wechat-capture:lab/item", None)),
    ("https://mp.weixin.qq.com/s?__biz=MzA5&mid=abc&idx=1", ("wechat-capture:lab/item", None)),
    ("https://example.com/s/AbC", ("wechat-capture:lab/item", None)),
    (None, ("wechat-capture:lab/item", None)),
])
def test_article_identity_uses_permanent_links_and_falls_back_to_capture_key(url, expected):
    assert article_identity(url, "lab/item") == expected


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
