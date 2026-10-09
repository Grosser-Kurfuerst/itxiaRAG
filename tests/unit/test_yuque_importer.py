import json
from dataclasses import replace
from datetime import date, datetime, timezone
from io import StringIO
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from config import components
from contracts.errors import DomainError
from contracts.types import ImportResult
from sources.yuque.client import YuqueDocRef, YuqueSnapshotClient
from sources.yuque.importer import SubmissionResult, YuqueImportService, build_request, clean_title
from sources.yuque.manifest import Manifest


@pytest.fixture
def snapshot(tmp_path):
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text('''version = 1
group = "synthetic"
[books.help]
visibility = "public"
[books.textbook]
visibility = "internal"
[[path_rules]]
book = "help"
path_prefix = ["工具"]
category = "tool_card"
[docs."help/install"]
category = "tutorial"
[docs."help/second"]
category = "tutorial"
[docs."help/copy"]
skip = "duplicate"
canonical = "help/install"
[docs."help/old"]
skip = "deprecated"
[docs."help/knowledge"]
category = "knowledge"
[docs."help/trouble"]
category = "troubleshooting"
[docs."help/missing"]
category = "tutorial"
[docs."textbook/install"]
category = "tutorial"
''', encoding="utf-8")
    directory = tmp_path / "snapshot"
    help_dir = directory / "help"
    help_dir.mkdir(parents=True)
    toc = [
        {"type": "TITLE", "title": "上级目录", "uuid": "root", "parent_uuid": "", "url": "", "doc_id": None},
        {"type": "DOC", "title": "父文档", "uuid": "parent", "parent_uuid": "root", "url": "parent", "doc_id": 100},
        {"type": "DOC", "title": "安装", "uuid": "install", "parent_uuid": "parent", "url": "install", "doc_id": 1},
        {"type": "TITLE", "title": "工具", "uuid": "tools", "parent_uuid": "", "url": "", "doc_id": None},
        {"type": "DOC", "title": "合成工具", "uuid": "tool", "parent_uuid": "tools", "url": "tool", "doc_id": 3},
        {"type": "LINK", "title": "外链", "uuid": "link", "parent_uuid": "root", "url": "https://example.com", "doc_id": None},
    ]
    slugs = ["install", "second", "tool", "copy", "new", "knowledge", "old", "trouble", "parent"]
    docs = [{"id": i, "slug": slug, "title": "【推送归档】教程 | 合成安装 ⭐⭐",
             "content_updated_at": "2025-11-23T18:23:51.000Z"} for i, slug in enumerate(slugs, 1)]
    docs[-1]["id"] = 100
    (help_dir / "toc.json").write_text(json.dumps({"data": toc}), encoding="utf-8")
    (help_dir / "docs.json").write_text(json.dumps({"data": docs}), encoding="utf-8")
    # 不可导入的条目故意没有正文文件；分类应该先于正文读取。
    for slug in ["install", "second"]:
        (help_dir / f"{slug}.md").write_text("## 安装篇\n\n先备份数据再安装。\n\n![](synthetic.png)", encoding="utf-8")
    internal = directory / "textbook"
    internal.mkdir()
    (internal / "toc.json").write_text('{"data": []}', encoding="utf-8")
    (internal / "docs.json").write_text(json.dumps({"data": [
        {"id": 20, "slug": "install", "title": "社内安装 ⭐", "content_updated_at": "2025-11-23T13:23:51Z"},
    ]}), encoding="utf-8")
    (internal / "install.md").write_text("## 安装\n\n合成社内教程。", encoding="utf-8")
    return directory, manifest_path


def test_snapshot_uses_openapi_envelope_and_doc_ancestors_without_self(snapshot):
    directory, _ = snapshot
    client = YuqueSnapshotClient(directory)
    refs = {ref.slug: ref for ref in client.list_docs("help")}
    assert refs["install"].toc_path == ("上级目录", "父文档")
    assert refs["parent"].toc_path == ("上级目录",)
    assert refs["tool"].toc_path == ("工具",)
    assert refs["second"].toc_path == ()
    assert refs["install"].content_updated_at == datetime(2025, 11, 23, 18, 23, 51, tzinfo=timezone.utc)
    assert client.read_markdown(refs["install"]).startswith("## 安装篇")


@pytest.mark.parametrize("title,expected", [
    ("【推送归档】教程 | Windows 安装 ⭐⭐", "Windows 安装"),
    ("【推送存档】Tips | 使用技巧", "使用技巧"),
    ("【推送存档】插件推荐 | Markdown Here", "Markdown Here"),
    ("【推送归档】| Why Not Kami?", "Why Not Kami?"),
    ("【日常整理】趣味向 ｜ 合成知识", "合成知识"),
    ("【栏目】【归档】清灰 ⭐ ⭐ ", "清灰"),
    ("  普通文档标题  ", "普通文档标题"),
    ("正文【方括号】与 ⭐ 保留", "正文【方括号】与 ⭐ 保留"),
])
def test_title_cleaning_is_limited_to_prefixes_and_trailing_stars(title, expected):
    assert clean_title(title) == expected


def test_request_identity_metadata_beijing_date_and_visibility(snapshot):
    directory, path = snapshot
    manifest = Manifest.load(path)
    ref = YuqueSnapshotClient(directory).list_docs("help")[0]
    request = build_request(ref, "合成正文\n", manifest, schema="tutorial", version=1)
    assert request["source"] == {
        "source_type": "yuque", "canonical_locator": "doc:1", "visibility": "public",
        "source_url": "https://www.yuque.com/synthetic/help/install",
    }
    metadata = request["raw"]["metadata"]
    assert metadata["source_date"] == "2025-11-24"  # UTC 晚间跨北京时间日期。
    assert metadata["collection_path"] == ["上级目录", "父文档"]
    assert metadata["title"] == "合成安装" and metadata["yuque"]["title_raw"] == ref.title
    assert metadata["yuque"] == {
        "doc_id": 1, "book": "help", "slug": "install", "title_raw": ref.title,
        "content_updated_at": "2025-11-23T18:23:51+00:00", "classified_by": "manifest",
    }
    internal = YuqueSnapshotClient(directory).list_docs("textbook")[0]
    assert build_request(internal, "正文", manifest, schema="tutorial", version=1)["source"]["visibility"] == "internal"
    manifest.docs["help/install"]["visibility"] = "internal"
    assert build_request(ref, "正文", manifest, schema="tutorial", version=1)["source"]["visibility"] == "internal"


def test_service_records_all_statuses_counts_warnings_and_continues_after_domain_error(snapshot):
    directory, path = snapshot
    client, manifest = YuqueSnapshotClient(directory), Manifest.load(path)
    registry = components.preprocessors()
    submitted = []

    def submit(source, raw, schema, version):
        submitted.append(source.canonical_locator)
        assert raw.metadata["source_date"] == date(2025, 11, 24)
        if source.canonical_locator == "doc:1":
            raise DomainError("SYNTHETIC_FAILURE", "合成失败")
        doc = registry.process(raw, schema, version)
        return SubmissionResult(doc, ImportResult(uuid4(), [uuid4()], reused=True))

    service = YuqueImportService(client, manifest, components.CATEGORY_PIPELINES, submit)
    report = service.run(client.list_docs("help"))
    rows = {row.doc: row for row in report.rows}
    assert submitted == ["doc:1", "doc:2"]
    assert rows["help/install"].status == "failed" and "SYNTHETIC_FAILURE" in rows["help/install"].detail
    assert rows["help/second"].status == "reused"
    assert rows["help/second"].parents == 1 and rows["help/second"].children == 1
    assert "原文含未转写的截图" in rows["help/second"].detail
    assert rows["help/new"].status == "unregistered"
    assert rows["help/copy"].detail == "duplicate → help/install"
    assert rows["help/old"].detail == "deprecated"
    for key in ["help/tool", "help/knowledge", "help/trouble"]:
        assert rows[key].status == "skipped" and rows[key].detail == "未接入"
    assert report.summary == {"imported": 0, "reused": 1, "preprocessed": 0, "skipped": 5, "unregistered": 2, "failed": 1}
    assert any("help/missing" in warning and "slug 可能已改名" in warning for warning in report.warnings)
    formatted = report.format()
    for text in ["category(by)", "parents", "children", "tool_card(path_rule)", "summary:"]:
        assert text in formatted
    assert "先备份数据再安装" not in formatted


def test_successful_submit_records_imported_and_only_suppresses_unrelated_missing_warnings(snapshot):
    directory, path = snapshot
    client = YuqueSnapshotClient(directory)
    registry = components.preprocessors()

    def submit(source, raw, schema, version):
        return SubmissionResult(registry.process(raw, schema, version), ImportResult(uuid4(), [uuid4()], False))

    report = YuqueImportService(client, Manifest.load(path), components.CATEGORY_PIPELINES, submit).run(
        client.list_docs("help"), only=["help/second", "help/missing"],
    )
    assert [row.status for row in report.rows] == ["imported"]
    assert len(report.warnings) == 1 and "help/missing" in report.warnings[0]


@pytest.mark.parametrize("reused,status", [(None, "preprocessed"), (False, "imported"), (True, "reused")])
def test_success_report_truncates_and_deduplicates_warnings_without_changing_document(snapshot, reused, status):
    directory, path = snapshot
    client = YuqueSnapshotClient(directory)
    registry = components.preprocessors()
    long_warning = "合成提示块：" + "提示内容" * 800
    boundary_warning = "短" * 30
    multiline_warning = "合成警告\n第二行"
    documents = []

    def submit(source, raw, schema, version):
        document = registry.process(raw, schema, version)
        parent = document.contexts[0]
        child = replace(parent.children[0], warnings=[long_warning, multiline_warning])
        parent = replace(parent, children=[child], warnings=[long_warning, boundary_warning])
        document = replace(document, contexts=[parent], warnings=[long_warning])
        documents.append(document)
        result = None if reused is None else ImportResult(uuid4(), [uuid4()], reused)
        return SubmissionResult(document, result)

    report = YuqueImportService(client, Manifest.load(path), components.CATEGORY_PIPELINES, submit).run(
        client.list_docs("help"), only=["help/install"],
    )
    assert report.rows[0].status == status
    assert report.rows[0].detail == "；".join([long_warning[:30] + "…", boundary_warning, multiline_warning])
    assert len(report.format().splitlines()) == 3  # 表头、单篇行、汇总。
    assert long_warning not in report.format()
    assert "先备份数据再安装" not in report.format()
    assert documents[0].warnings == [long_warning]
    assert documents[0].contexts[0].children[0].warnings == [long_warning, multiline_warning]


def test_bad_request_or_missing_markdown_is_a_per_document_failure(snapshot):
    directory, path = snapshot
    client = YuqueSnapshotClient(directory)
    refs = client.list_docs("help")[:2]
    (directory / "help/install.md").write_text("", encoding="utf-8")
    (directory / "help/second.md").unlink()
    submit = Mock()
    report = YuqueImportService(client, Manifest.load(path), components.CATEGORY_PIPELINES, submit).run(refs)
    assert [row.status for row in report.rows] == ["failed", "failed"]
    assert "INVALID_REQUEST" in report.rows[0].detail
    assert "SNAPSHOT_READ_FAILED" in report.rows[1].detail
    submit.assert_not_called()


@pytest.mark.parametrize("filename,content", [
    ("toc.json", "[]"), ("docs.json", '{"data": {}}'), ("docs.json", "{"),
    ("docs.json", '{"data": [{"id": 1}]}'),
])
def test_snapshot_metadata_errors_are_clear(snapshot, filename, content):
    directory, _ = snapshot
    (directory / "help" / filename).write_text(content, encoding="utf-8")
    with pytest.raises(DomainError) as error:
        YuqueSnapshotClient(directory).list_docs("help")
    assert error.value.code == "INVALID_SNAPSHOT"


def test_command_dry_run_needs_no_account_database_embedding_or_store(snapshot):
    directory, path = snapshot
    output = StringIO()
    with patch("config.components.embedding_provider") as embedder, \
            patch("config.components.document_store") as store, \
            patch("sources.management.commands.import_yuque.get_user_model") as users:
        call_command("import_yuque", manifest=str(path), snapshot=str(directory), dry_run=True, stdout=output)
    embedder.assert_not_called()
    store.assert_not_called()
    users.assert_not_called()
    assert "preprocessed=3" in output.getvalue() and "failed=0" in output.getvalue()
    assert "tutorial(manifest)" in output.getvalue() and "未接入" in output.getvalue()
    assert "合成社内教程" not in output.getvalue()


def test_command_only_reads_selected_books_and_only_reports_selected_docs(snapshot):
    directory, path = snapshot
    (directory / "textbook/docs.json").unlink()
    output = StringIO()
    call_command("import_yuque", manifest=str(path), snapshot=str(directory), dry_run=True,
                 only=["help/install", "help/second"], stdout=output)
    assert "preprocessed=2" in output.getvalue()
    assert "warning:" not in output.getvalue() and "textbook/" not in output.getvalue()


def test_command_dry_run_with_account_enforces_internal_permissions_and_finishes_batch(snapshot):
    directory, path = snapshot
    actor = Mock(is_authenticated=True, is_active=True)
    actor.has_perm.side_effect = lambda permission: permission == "catalog.maintain_source"
    output = StringIO()
    with patch("sources.management.commands.import_yuque.get_user_model") as users:
        users.return_value.objects.get.return_value = actor
        with pytest.raises(CommandError, match="1 篇失败"):
            call_command("import_yuque", manifest=str(path), snapshot=str(directory), dry_run=True,
                         username="maintainer", stdout=output)
    assert "NOT_FOUND" in output.getvalue() and "preprocessed=2" in output.getvalue()


def test_command_formal_import_uses_raw_main_chain_once_per_doc_and_reports_counts(snapshot, embedder):
    directory, path = snapshot
    actor = Mock(is_authenticated=True, is_active=True, has_perm=Mock(return_value=True))
    registry = components.preprocessors()
    store = Mock()
    store.save.side_effect = lambda *args: ImportResult(uuid4(), [uuid4()], False)
    output = StringIO()
    with patch("sources.management.commands.import_yuque.get_user_model") as users, \
            patch("config.components.embedding_provider", return_value=embedder), \
            patch("config.components.document_store", return_value=store), \
            patch("config.components.preprocessors", return_value=registry), \
            patch.object(registry, "process", wraps=registry.process) as process, \
            patch.object(embedder, "embed_documents", wraps=embedder.embed_documents) as embed:
        users.return_value.objects.get.return_value = actor
        call_command("import_yuque", manifest=str(path), snapshot=str(directory), username="maintainer", stdout=output)
    assert process.call_count == embed.call_count == store.save.call_count == 3
    assert "imported=3" in output.getvalue() and "preprocessed=0" in output.getvalue()
    source, document, vectors, space, saved_actor = store.save.call_args.args
    assert source.canonical_locator == "doc:20" and source.visibility == "internal"
    assert document.document_schema == "tutorial" and document.title == "社内安装"
    assert len(vectors) == sum(len(parent.children) for parent in document.contexts)
    assert space == embedder.space_id and saved_actor is actor


@pytest.mark.parametrize("failure", ["permission", "preprocessing"])
def test_command_formal_import_failure_happens_before_embedding_or_save(snapshot, failure):
    directory, path = snapshot
    actor = Mock(is_authenticated=True, is_active=True)
    actor.has_perm.side_effect = lambda permission: (
        permission == "catalog.maintain_source" or failure != "permission"
    )
    registry = Mock()
    message = "合成失败消息：" + "保留完整消息" * 20
    registry.process.side_effect = DomainError("SYNTHETIC_FAILURE", message)
    output = StringIO()
    with patch("sources.management.commands.import_yuque.get_user_model") as users, \
            patch("config.components.preprocessors", return_value=registry), \
            patch("config.components.embedding_provider") as embedder, \
            patch("config.components.document_store") as store:
        users.return_value.objects.get.return_value = actor
        with pytest.raises(CommandError, match="1 篇失败"):
            call_command("import_yuque", manifest=str(path), snapshot=str(directory), username="maintainer",
                         only=["textbook/install"], stdout=output)
    embedder.return_value.embed_documents.assert_not_called()
    store.return_value.save.assert_not_called()
    if failure == "permission":
        registry.process.assert_not_called()
        assert "NOT_FOUND: 对象不存在" in output.getvalue()
    else:
        registry.process.assert_called_once()
        assert f"SYNTHETIC_FAILURE: {message}" in output.getvalue()


def test_command_bad_manifest_fails_before_listing_or_submitting(snapshot):
    directory, path = snapshot
    path.write_text('version = 1\ngroup = "synthetic"\nunknown = true', encoding="utf-8")
    with patch.object(YuqueSnapshotClient, "list_docs") as listing, \
            patch("config.components.embedding_provider") as embedder:
        with pytest.raises(CommandError, match="未知字段"):
            call_command("import_yuque", manifest=str(path), snapshot=str(directory), username="maintainer")
    listing.assert_not_called()
    embedder.assert_not_called()


def test_command_missing_snapshot_or_username_and_invalid_only_fail_at_startup(snapshot):
    directory, path = snapshot
    for options, message in [
        ({"dry_run": True}, "OpenAPI 读取尚未实现"),
        ({"snapshot": str(directory)}, "--username"),
        ({"snapshot": str(directory), "dry_run": True, "only": ["unknown/doc"]}, "--only"),
    ]:
        with pytest.raises(CommandError, match=message):
            call_command("import_yuque", manifest=str(path), **options)


def test_command_missing_embedding_configuration_fails_before_account_lookup_or_listing(snapshot, settings):
    directory, path = snapshot
    settings.EMBEDDING = {"base_url": "", "model": "", "dimensions": 0, "revision": ""}
    with patch.object(YuqueSnapshotClient, "list_docs") as listing, \
            patch("sources.management.commands.import_yuque.get_user_model") as users:
        with pytest.raises(CommandError, match="EMBEDDING_NOT_CONFIGURED"):
            call_command("import_yuque", manifest=str(path), snapshot=str(directory), username="maintainer")
    listing.assert_not_called()
    users.assert_not_called()
