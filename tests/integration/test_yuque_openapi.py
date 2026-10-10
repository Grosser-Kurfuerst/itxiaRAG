"""用本地 HTTP 服务验收语雀协议；不访问真实语雀或使用真实 Token。"""
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError

from catalog.models import KnowledgeSource
from sources.yuque.client import YuqueOpenApiClient, YuqueSnapshotClient


pytestmark = pytest.mark.integration
TEST_TOKEN = "synthetic-yuque-token-for-local-http-only"


def doc(doc_id, slug):
    return {"id": doc_id, "slug": slug, "title": "【归档】教程 | 合成安装 ⭐",
            "content_updated_at": "2025-11-23T18:23:51.000Z"}


@pytest.fixture
def yuque_server():
    state = SimpleNamespace(requests=[], responses={}, docs={
        "help": [doc(index, slug) for index, slug in enumerate(
            ["install", "second", "parent", "tool", "case", "trouble", "copy", "new"], 1)],
        "textbook": [doc(20, "case"), doc(21, "install")],
    }, toc={
        "help": [
            {"type": "TITLE", "title": "教程", "uuid": "root", "parent_uuid": "", "url": "", "doc_id": None},
            {"type": "DOC", "title": "父文档", "uuid": "parent", "parent_uuid": "root", "url": "parent", "doc_id": 3},
            {"type": "DOC", "title": "安装", "uuid": "install", "parent_uuid": "parent", "url": "install", "doc_id": 1},
            {"type": "TITLE", "title": "工具", "uuid": "tools", "parent_uuid": "", "url": "", "doc_id": None},
            {"type": "DOC", "title": "工具", "uuid": "tool", "parent_uuid": "tools", "url": "tool", "doc_id": 4},
        ],
        "textbook": [],
    })

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state.requests.append((self.path, dict(self.headers)))
            parsed = urlsplit(self.path)
            parts = parsed.path.split("/")
            book, resource = parts[5], parts[6]
            status = 200
            if parsed.path in state.responses:
                status, payload = state.responses[parsed.path]
            elif resource == "toc":
                payload = {"data": state.toc[book]}
            elif len(parts) == 7:
                query = parse_qs(parsed.query)
                offset, limit = int(query["offset"][0]), int(query["limit"][0])
                payload = {"data": state.docs[book][offset:offset + limit]}
            else:
                payload = {"data": {"body": "## 安装篇\n\n合成正文：先备份数据，再检查电池续航。",
                                    "body_draft": "不应导入的合成草稿"}}
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload if isinstance(payload, bytes) else json.dumps(payload).encode())

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/v2", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def openapi_command(tmp_path, settings, yuque_server):
    base_url, state = yuque_server
    settings.YUQUE_TOKEN, settings.YUQUE_API_BASE = TEST_TOKEN, base_url
    manifest = tmp_path / "manifest.toml"
    manifest.write_text('''version = 2
source_type = "yuque"
[connector]
group = "synthetic"
[collections.help]
visibility = "public"
[collections.textbook]
visibility = "internal"
[[path_rules]]
collection = "help"
path_prefix = ["工具"]
category = "tool_card"
[docs."help/install"]
category = "tutorial"
[docs."help/second"]
category = "tutorial"
[docs."help/case"]
category = "case"
[docs."help/trouble"]
category = "troubleshooting"
[docs."help/copy"]
skip = "duplicate"
canonical = "help/install"
[docs."textbook/case"]
category = "case"
[docs."textbook/install"]
category = "tutorial"
''', encoding="utf-8")

    def client(*args):
        return YuqueOpenApiClient(*args, interval=0)

    with patch("sources.management.commands.import_yuque.YuqueOpenApiClient", side_effect=client):
        yield manifest, state


def test_openapi_paths_headers_pagination_and_shared_ancestor_paths(yuque_server, tmp_path):
    base_url, state = yuque_server
    state.docs["help"].extend(doc(index, f"extra-{index}") for index in range(9, 102))
    client = YuqueOpenApiClient(base_url + "/", TEST_TOKEN, "synthetic", interval=0)
    refs = client.list_docs("help")
    assert len(refs) == 101 and refs[-1].slug == "extra-101"
    assert refs[0].toc_path == ("教程", "父文档")
    assert refs[2].toc_path == ("教程",) and refs[1].toc_path == ()
    assert refs[0].content_updated_at == datetime(2025, 11, 23, 18, 23, 51, tzinfo=timezone.utc)
    assert "合成正文" in client.read_markdown(refs[0])
    assert [path for path, _ in state.requests] == [
        "/api/v2/repos/synthetic/help/toc",
        "/api/v2/repos/synthetic/help/docs?offset=0&limit=100",
        "/api/v2/repos/synthetic/help/docs?offset=100&limit=100",
        "/api/v2/repos/synthetic/help/docs/install",
    ]
    assert all(headers["X-Auth-Token"] == TEST_TOKEN and headers["Accept"] == "application/json"
               and headers["User-Agent"] for _, headers in state.requests)
    assert client.save_snapshot(tmp_path, [refs[0]]) == {}
    snapshot = YuqueSnapshotClient(tmp_path)
    assert snapshot.list_docs("help") == refs
    assert snapshot.read_markdown(refs[0]) == client.read_markdown(refs[0])


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("resource", ["toc", "docs/install"])
def test_authentication_failure_terminates_command_before_processing(openapi_command, status, resource, caplog):
    manifest, state = openapi_command
    state.responses[f"/api/v2/repos/synthetic/help/{resource}"] = (status, {"message": TEST_TOKEN})
    output = StringIO()
    with patch("config.components.preprocessors") as registry:
        with pytest.raises(CommandError, match="检查 YUQUE_TOKEN 与知识库权限") as error:
            call_command("import_yuque", manifest=str(manifest), dry_run=True, stdout=output)
    registry.return_value.process.assert_not_called()
    assert not any("docs/second" in path for path, _ in state.requests)
    assert TEST_TOKEN not in str(error.value) + output.getvalue() + caplog.text


@pytest.mark.parametrize("save_snapshot", [False, True])
def test_rate_limit_is_one_failed_document_and_others_continue(openapi_command, tmp_path, caplog, save_snapshot):
    manifest, state = openapi_command
    state.responses["/api/v2/repos/synthetic/help/docs/install"] = (429, {"message": TEST_TOKEN})
    options = {"save_snapshot": str(tmp_path / "saved")} if save_snapshot else {}
    output = StringIO()
    with pytest.raises(CommandError, match="1 篇失败") as error:
        call_command("import_yuque", manifest=str(manifest), dry_run=True, stdout=output, **options)
    report = output.getvalue()
    assert "YUQUE_RATE_LIMITED" in report and "failed=1" in report and "preprocessed=2" in report
    assert any(path.endswith("/docs/second") for path, _ in state.requests)
    assert TEST_TOKEN not in str(error.value) + report + caplog.text


@pytest.mark.parametrize("payload", [{"data": {}}, {"data": {"body": None}}, b"invalid JSON"])
def test_invalid_detail_response_is_a_per_document_failure(openapi_command, payload):
    manifest, state = openapi_command
    state.responses["/api/v2/repos/synthetic/help/docs/install"] = (200, payload)
    output = StringIO()
    with pytest.raises(CommandError, match="1 篇失败"):
        call_command("import_yuque", manifest=str(manifest), dry_run=True, stdout=output)
    assert "INVALID_YUQUE_RESPONSE" in output.getvalue() and "preprocessed=2" in output.getvalue()


def test_list_failure_terminates_before_any_document_processing(openapi_command):
    manifest, state = openapi_command
    state.responses["/api/v2/repos/synthetic/textbook/docs"] = (429, {"message": TEST_TOKEN})
    with patch("config.components.preprocessors") as registry:
        with pytest.raises(CommandError, match="YUQUE_RATE_LIMITED"):
            call_command("import_yuque", manifest=str(manifest), dry_run=True)
    registry.return_value.process.assert_not_called()
    assert not any(len(urlsplit(path).path.split("/")) == 8 for path, _ in state.requests)


def test_snapshot_covers_all_classified_books_despite_only_and_can_be_imported_offline(
        openapi_command, tmp_path, settings, caplog):
    manifest, state = openapi_command
    additional = [doc(200 + index, f"case-{index}") for index in range(67)]
    state.docs["help"].extend(additional)
    with manifest.open("a", encoding="utf-8") as stream:
        for item in additional:
            stream.write(f'\n[docs."help/{item["slug"]}"]\ncategory = "case"\n')
    directory, output = tmp_path / "saved", StringIO()
    call_command("import_yuque", manifest=str(manifest), dry_run=True, only=["help/install"],
                 save_snapshot=str(directory), stdout=output)
    assert "preprocessed=1" in output.getvalue()
    assert len(list(directory.rglob("*.md"))) == 74
    snapshot = YuqueSnapshotClient(directory)
    for book, slugs in [("help", {"install", "second", "tool", "case", "trouble"}),
                        ("textbook", {"install", "case"})]:
        if book == "help":
            slugs |= {item["slug"] for item in additional}
        refs = snapshot.list_docs(book)
        assert json.loads((directory / book / "toc.json").read_text()) == {"data": state.toc[book]}
        assert json.loads((directory / book / "docs.json").read_text()) == {"data": state.docs[book]}
        for ref in refs:
            assert (directory / book / f"{ref.slug}.md").exists() == (ref.slug in slugs)
            if ref.slug in slugs:
                assert "合成正文" in snapshot.read_markdown(ref)
    assert TEST_TOKEN not in output.getvalue() + caplog.text
    assert all(TEST_TOKEN not in path.read_text() for path in directory.rglob("*") if path.is_file())
    assert all("不应导入的合成草稿" not in path.read_text() for path in directory.rglob("*.md"))
    before = len(state.requests)
    settings.YUQUE_TOKEN = ""
    offline = StringIO()
    call_command("import_yuque", manifest=str(manifest), snapshot=str(directory), dry_run=True, stdout=offline)
    assert "preprocessed=3" in offline.getvalue() and "failed=0" in offline.getvalue()
    assert len(state.requests) == before


def test_snapshot_failure_for_unselected_unimplemented_category_is_reported(openapi_command, tmp_path):
    manifest, state = openapi_command
    state.responses["/api/v2/repos/synthetic/textbook/docs/case"] = (500, {"message": TEST_TOKEN})
    output = StringIO()
    with pytest.raises(CommandError, match="1 篇失败"):
        call_command("import_yuque", manifest=str(manifest), dry_run=True, only=["help/install"],
                     save_snapshot=str(tmp_path / "saved"), stdout=output)
    assert "textbook/case" in output.getvalue() and "YUQUE_UNAVAILABLE" in output.getvalue()
    assert "failed=1" in output.getvalue() and "preprocessed=1" in output.getvalue()


def test_missing_token_and_conflicting_snapshot_modes_fail_before_requests(openapi_command, settings, tmp_path):
    manifest, state = openapi_command
    settings.YUQUE_TOKEN = ""
    for options, message in [({}, "YUQUE_TOKEN"),
                             ({"snapshot": str(tmp_path), "save_snapshot": str(tmp_path)}, "互斥")]:
        with pytest.raises(CommandError, match=message):
            call_command("import_yuque", manifest=str(manifest), dry_run=True, **options)
    assert state.requests == []


@pytest.mark.django_db
def test_openapi_formal_import_and_reimport_use_main_chain_and_reuse_sources(openapi_command, embedder):
    manifest, _ = openapi_command
    actor = get_user_model().objects.create_user("yuque-openapi-maintainer")
    actor.user_permissions.set(Permission.objects.filter(
        content_type__app_label="catalog", codename__in=["maintain_source", "read_internal"],
    ))
    first, repeated = StringIO(), StringIO()
    with patch("config.components.embedding_provider", return_value=embedder):
        call_command("import_yuque", manifest=str(manifest), username=actor.username, stdout=first)
        sources = list(KnowledgeSource.objects.order_by("canonical_locator"))
        assert {source.canonical_locator for source in sources} == {"doc:1", "doc:2", "doc:21"}
        assert all(source.source_type == "yuque" and source.document_schema == "tutorial" for source in sources)
        assert KnowledgeSource.objects.get(canonical_locator="doc:1").metadata["collection_path"] == ["教程", "父文档"]
        call_command("import_yuque", manifest=str(manifest), username=actor.username, stdout=repeated)
    assert "imported=3" in first.getvalue() and "reused=3" in repeated.getvalue()
    assert KnowledgeSource.objects.count() == 3
