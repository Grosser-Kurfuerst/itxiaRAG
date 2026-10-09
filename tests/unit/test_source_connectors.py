"""所有 SourceConnector 实现共用的契约：新增平台时在 CONNECTORS 中登记一个合成数据构造函数。"""
import json
from datetime import date
from urllib.parse import urlsplit

import pytest

from contracts.errors import DomainError, SourceAccessError
from contracts.serializers import RawSourceImportSerializer
from sources.importing import build_request
from sources.manifest import Classification, Manifest
from sources.wechat.connector import WechatCaptureConnector
from sources.yuque.client import YuqueSnapshotClient
from sources.yuque.connector import YuqueConnector


def yuque_connector(root):
    for book, base in [("help", 1), ("textbook", 100)]:
        directory = root / book
        directory.mkdir(parents=True)
        toc = [{"type": "TITLE", "title": "合成目录", "uuid": "dir", "parent_uuid": "", "url": "", "doc_id": None},
               {"type": "DOC", "title": "合成", "uuid": "a", "parent_uuid": "dir", "url": "a", "doc_id": base}]
        docs = [{"id": base + index, "slug": slug, "title": f"【推送归档】合成 {slug} ⭐",
                 "content_updated_at": "2025-11-23T18:23:51.000Z"} for index, slug in enumerate(["a", "b"])]
        (directory / "toc.json").write_text(json.dumps({"data": toc}), encoding="utf-8")
        (directory / "docs.json").write_text(json.dumps({"data": docs}), encoding="utf-8")
        for slug in ["a", "b"]:
            (directory / f"{slug}.md").write_text(f"## 合成 {slug}\n\n合成正文。", encoding="utf-8")
    return YuqueConnector(YuqueSnapshotClient(root), "synthetic", ["help", "textbook"]), "md"


def wechat_connector(root):
    for account, items in [("lab-a", [("p1", "https://mp.weixin.qq.com/s?__biz=MzA=&mid=1&idx=1&sn=x"),
                                      ("p2", None)]),
                           ("lab-b", [("p1", "https://mp.weixin.qq.com/s/Abc")])]:
        directory = root / account
        directory.mkdir(parents=True)
        for name, url in items:
            (directory / f"{name}.html").write_text("<h2>合成</h2><p>合成正文。</p>", encoding="utf-8")
            sidecar = {"title": f"合成 {name}", "date": "2026-09-28", **({"url": url} if url else {})}
            (directory / f"{name}.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return WechatCaptureConnector(root, ["lab-a", "lab-b"]), "html"


CONNECTORS = [yuque_connector, wechat_connector]


@pytest.fixture(params=CONNECTORS, ids=lambda build: build.__name__)
def built(request, tmp_path):
    connector, suffix = request.param(tmp_path)
    return connector, suffix, tmp_path


def manifest_for(connector, refs):
    return Manifest({
        "version": 2, "source_type": connector.source_type,
        "collections": {ref.collection: {"visibility": "public"} for ref in refs},
    }, source_type=connector.source_type, categories={"synthetic"})


def test_list_is_stable_with_unique_keys_and_identities(built):
    connector, _, _ = built
    refs = list(connector.list())
    assert len(refs) >= 3 and len({ref.collection for ref in refs}) == 2
    assert refs == list(connector.list())
    assert len({ref.key for ref in refs}) == len({ref.canonical_locator for ref in refs}) == len(refs)
    for ref in refs:
        collection, item = ref.key.split("/")
        assert collection == ref.collection and item
        assert ref.title.strip() and ref.canonical_locator.strip()


def test_fetched_sources_build_requests_that_pass_the_raw_import_contract(built):
    connector, _, _ = built
    refs = list(connector.list())
    manifest = manifest_for(connector, refs)
    for ref in refs:
        fetched = connector.fetch(ref)
        assert fetched.ref == ref
        assert fetched.source_url is None or urlsplit(fetched.source_url).scheme == "https"
        metadata = fetched.raw.metadata
        assert isinstance(metadata["title"], str) and metadata["title"].strip()
        if metadata.get("source_date") is not None:
            date.fromisoformat(metadata["source_date"])
        assert isinstance(metadata[connector.source_type], dict)
        request = build_request(connector.source_type, fetched, manifest, schema="synthetic", version=1,
                                classification=Classification("synthetic", "manifest"))
        serializer = RawSourceImportSerializer(data=request)
        assert serializer.is_valid(), serializer.errors
        assert request["source"]["canonical_locator"] == ref.canonical_locator


def test_single_document_read_failure_is_a_domain_error_not_a_batch_abort(built):
    connector, suffix, root = built
    ref = list(connector.list())[0]
    (root / f"{ref.key}.{suffix}").unlink()
    with pytest.raises(DomainError):
        connector.fetch(ref)
    assert not issubclass(DomainError, SourceAccessError)
