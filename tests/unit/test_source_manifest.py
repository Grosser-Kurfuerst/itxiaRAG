from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
import re

import pytest

from config.components import YUQUE_CATEGORY_PIPELINES
from contracts.types import SourceRef
from sources.manifest import Classification, Manifest, ManifestError
from sources.yuque.connector import CATEGORIES


def ref(key="help/install", path=()):
    collection = key.split("/")[0]
    return SourceRef(collection, key, "doc:1", "合成标题", tuple(path), datetime(2025, 1, 1, tzinfo=timezone.utc))


def load(data):
    return Manifest(data, source_type="yuque", categories=CATEGORIES)


def manifest_data():
    return {
        "version": 2, "source_type": "yuque", "connector": {"group": "synthetic"},
        "collections": {"help": {"visibility": "public"}, "textbook": {"visibility": "internal"}},
        "path_rules": [
            {"collection": "help", "path_prefix": ["工具"], "category": "tool_card"},
            {"collection": "help", "path_prefix": ["工具", "安装"], "category": "tutorial"},
        ],
        "docs": {
            "help/install": {"category": "knowledge", "visibility": "internal"},
            "help/copy": {"skip": "duplicate", "canonical": "help/install"},
            "help/old": {"skip": "deprecated"},
            "help/trouble": {"category": "troubleshooting", "metadata": {"entity_title": "合成"}},
            "textbook/case": {"category": "case", "visibility": "public"},
        },
    }


def test_single_doc_overrides_path_rules_and_longest_prefix_is_scoped_to_collection():
    manifest = load(manifest_data())
    assert manifest.classify(ref(path=["工具", "安装"])) == Classification("knowledge", "manifest")
    assert manifest.classify(ref("help/new", ["工具", "安装", "子目录"])) == Classification("tutorial", "path_rule")
    assert manifest.classify(ref("help/new", ["工具", "安装指南"])) == Classification("tool_card", "path_rule")
    assert manifest.classify(ref("textbook/new", ["工具", "安装"])) == Classification(None, "none")
    assert manifest.classify(ref("help/new", ["其他", "工具"])) == Classification(None, "none")


def test_skip_unregistered_and_known_but_unconnected_categories_are_distinct():
    manifest = load(manifest_data())
    assert manifest.classify(ref("help/copy", ["工具"])) == Classification(None, "manifest", "duplicate")
    assert manifest.canonical_for(ref("help/copy")) == "help/install"
    assert manifest.classify(ref("help/old")).skip == "deprecated"
    assert manifest.classify(ref("help/new")) == Classification(None, "none")
    for key, category in [("help/trouble", "troubleshooting"), ("textbook/case", "case")]:
        assert manifest.classify(ref(key)) == Classification(category, "manifest")
        assert category not in YUQUE_CATEGORY_PIPELINES


def test_visibility_uses_document_override_then_collection_default():
    manifest = load(manifest_data())
    assert manifest.collections == ["help", "textbook"]
    assert manifest.visibility_for(ref()) == "internal"
    assert manifest.visibility_for(ref("help/new")) == "public"
    assert manifest.visibility_for(ref("textbook/new")) == "internal"
    assert manifest.visibility_for(ref("textbook/case")) == "public"


@pytest.mark.parametrize("location,change,message", [
    ((), {"extra": 1}, "未知字段"),
    ((), {"version": True}, "version"),
    ((), {"version": 1}, "version"),
    ((), {"source_type": "wechat"}, "source_type"),
    ((), {"connector": []}, "connector"),
    ((), {"collections": {}}, "collections"),
    ((), {"collections": {"a/b": {"visibility": "public"}}}, "集合标识"),
    ((), {"docs": []}, "docs"),
    ((), {"path_rules": {}}, "path_rules"),
    (("collections", "help"), {"extra": 1}, "未知字段"),
    (("collections", "help"), {"visibility": "private"}, "visibility"),
    (("docs", "help/install"), {"extra": 1}, "未知字段"),
    (("docs", "help/install"), {"category": "unknown"}, "category"),
    (("docs", "help/install"), {"skip": "duplicate"}, "category 或 skip"),
    (("docs", "help/install"), {"visibility": "private"}, "visibility"),
    (("docs", "help/copy"), {"canonical": "help/missing"}, "不存在"),
    (("docs", "help/copy"), {"canonical": []}, "不存在"),
    (("docs", "help/copy"), {"skip": ""}, "skip"),
    (("docs", "help/install"), {"canonical": "help/copy"}, "只能用于 skip"),
    (("docs", "help/old"), {"metadata": {}}, "metadata"),
    (("docs", "help/install"), {"metadata": []}, "metadata"),
    (("docs", "help/install"), {"metadata": {"yuque": {}}}, "平台字段"),
    (("docs", "help/install"), {"metadata": {"reviewed_on": date(2026, 9, 28)}}, "日期请写成文本"),
    (("path_rules", 0), {"extra": 1}, "未知字段"),
    (("path_rules", 0), {"collection": "missing"}, "collection"),
    (("path_rules", 0), {"category": "unknown"}, "category"),
    (("path_rules", 0), {"path_prefix": "工具"}, "path_prefix"),
    (("path_rules", 0), {"path_prefix": []}, "path_prefix"),
    (("path_rules", 0), {"path_prefix": [1]}, "path_prefix"),
    (("path_rules", 0), {"path_prefix": [" "]}, "path_prefix"),
])
def test_manifest_rejects_invalid_fields_before_processing(location, change, message):
    data = manifest_data()
    target = data
    for key in location:
        target = target[key]
    target.update(change)
    with pytest.raises(ManifestError, match=message):
        load(data)


def test_manifest_rejects_missing_decision_and_ambiguous_directory_rules():
    data = manifest_data()
    data["docs"]["help/install"] = {"visibility": "public"}
    with pytest.raises(ManifestError, match="category 或 skip"):
        load(data)
    data = manifest_data()
    data["path_rules"].append(deepcopy(data["path_rules"][0]))
    with pytest.raises(ManifestError, match="重复登记"):
        load(data)


def test_metadata_patch_is_copied_and_docs_must_use_registered_collection():
    manifest = load(manifest_data())
    patch = manifest.metadata_for(ref("help/trouble"))
    assert patch == {"entity_title": "合成"}
    patch["entity_title"] = "改动"
    assert manifest.metadata_for(ref("help/trouble")) == {"entity_title": "合成"}
    assert manifest.metadata_for(ref("help/new")) == {}
    data = manifest_data()
    data["docs"]["other/doc"] = {"category": "tutorial"}
    with pytest.raises(ManifestError, match="集合未登记"):
        load(data)


def test_toml_syntax_error_has_clear_manifest_error(tmp_path):
    path = tmp_path / "invalid.toml"
    path.write_text("version = [", encoding="utf-8")
    with pytest.raises(ManifestError, match="无法读取导入清单"):
        Manifest.load(path, source_type="yuque", categories=CATEGORIES)


def test_repository_manifest_classifies_all_74_appendix_docs():
    root = Path(__file__).resolve().parents[2]
    manifest = Manifest.load(root / "sources/yuque/manifests/itxia.toml", source_type="yuque",
                             categories=CATEGORIES)
    appendix = (root / "docs/phase1/yuque-ingestion/requirements-analysis.md").read_text().split(
        "## 附录：第一批文档清单初稿", 1,
    )[1]
    counts = Counter()
    for heading, category in [("操作教程", "tutorial"), ("工具条目", "tool_card"),
                              ("知识科普／对比／速查", "knowledge")]:
        section = appendix.split("### " + heading, 1)[1].split("\n### ", 1)[0]
        for line in section.splitlines():
            match = re.match(r"\| ([a-z0-9_-]+/[a-z0-9_-]+) \|", line)
            if not match:
                continue
            key = match[1]
            path_text = line.split(" | ")[-2]
            path = [] if path_text == "—" else path_text.split(" > ")
            classification = manifest.classify(ref(key, path))
            assert classification.category == category, key
            assert classification.skip is None
            assert classification.decided_by == (
                "path_rule" if category == "tool_card" and key.startswith("help/") else "manifest"
            )
            counts[category] += 1
    assert counts == {"tutorial": 28, "tool_card": 31, "knowledge": 15}
    assert len(manifest.docs) == 49  # 46 个单篇分类 + 3 个重复副本。
    assert manifest.collections == ["help", "article", "textbook", "basic-computer", "dygh8t"]
    assert manifest.visibility_for(ref("textbook/make_pe")) == "internal"
    for slug in ["partition-resize", "install_win10_from_scratch", "gagpcm"]:
        duplicate = ref(f"article/{slug}")
        assert manifest.classify(duplicate).skip == "duplicate"
        assert manifest.canonical_for(duplicate) in manifest.docs
    assert manifest.canonical_for(ref("article/partition-resize")) == "help/partition-resize"
    assert manifest.canonical_for(ref("article/install_win10_from_scratch")) == "help/install_win10"
    assert manifest.canonical_for(ref("article/gagpcm")) == "help/nju_network_guide"
