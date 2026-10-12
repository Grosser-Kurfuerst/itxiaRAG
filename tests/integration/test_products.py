import json

import pytest
from django.core.management import CommandError, call_command

from catalog.models import ContextUnit
from catalog.storage import DjangoDocumentStore
from contracts.serializers import SourceImportSerializer, import_dtos
from ingestion.pipeline import import_processed
from products.importing import import_specs
from products.models import ProductSpec

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

PORTS = {"usb_a": True, "usb_c": True, "video_out": True, "hdmi": True,
         "rj45": False, "card_reader": False, "thunderbolt": False, "oculink": False}


@pytest.fixture
def review(document_payload, embedder):
    """合成评测：父段标题“笔记本 A”，正文含“日常办公续航约 8 小时”。"""
    serializer = SourceImportSerializer(data=document_payload)
    serializer.is_valid(raise_exception=True)
    import_processed(*import_dtos(serializer.validated_data), embedder=embedder, store=DjangoDocumentStore())
    return ContextUnit.objects.get(title="笔记本 A")


def spec(key="笔记本 A", **fields):
    return {"key": key, "brand": "示例", "price_cny": 5999, "price_kind": "reference",
            "battery_hours": 8, "ports": PORTS, "evidence": {"battery_hours": "日常办公续航 约8小时"}, **fields}


def test_import_links_review_and_reports_changes(review):
    report = import_specs([spec()], dry_run=True)
    assert report.created == ["笔记本 A"] and not ProductSpec.objects.exists()

    report = import_specs([spec(), spec("无评测机型", evidence={})])
    assert (report.created, report.unlinked) == (["笔记本 A", "无评测机型"], ["无评测机型"])
    assert ProductSpec.objects.get(key="笔记本 A").review_context == review
    assert ProductSpec.objects.get(key="无评测机型").review_context is None

    assert import_specs([spec(), spec("无评测机型", evidence={})]).unchanged == ["笔记本 A", "无评测机型"]

    report = import_specs([spec("笔记本 A ", price_cny=5799)])
    assert (report.updated, report.deleted) == (["笔记本 A"], ["无评测机型"])
    assert list(ProductSpec.objects.values_list("key", "price_cny")) == [("笔记本 A", 5799)]


def test_renamed_review_is_reported_as_unlinked(review):
    import_specs([spec(evidence={})])
    review.title = "笔记本 A 新标题"
    review.save()

    report = import_specs([spec(evidence={})])

    assert (report.updated, report.unlinked) == (["笔记本 A"], ["笔记本 A"])
    assert ProductSpec.objects.get().review_context is None


def test_any_failure_keeps_whole_file_out_of_database(review):
    import_specs([spec("笔记本 C", evidence={})])
    report = import_specs([
        spec(evidence={**spec()["evidence"], "cpu": {"source": "https://example.com", "quote": "不检查正文"}}),
        spec("笔记本 B", evidence={"weight_kg": "原文中没有这句"}),
        spec("笔记本 C", has_dgpu=False, gpu="RTX 4060"),
        spec(),
        "不是对象",
    ])

    assert (report.created, report.deleted) == (["笔记本 A"], [])
    assert len(report.failed) == 4
    assert "笔记本 B：没有评测父段，无法校验原文引用：weight_kg" in report.failed
    assert any(item.startswith("笔记本 A：key 重复") for item in report.failed)
    assert "第 5 条：必须是 JSON 对象" in report.failed
    assert list(ProductSpec.objects.values_list("key", flat=True)) == ["笔记本 C"]


def test_quote_must_appear_in_review_and_title_must_be_unique(review):
    report = import_specs([spec(evidence={"weight_kg": "原文中没有这句"})])
    assert report.failed == ["笔记本 A：引用不在评测正文中：weight_kg"]

    ContextUnit.objects.create(source=review.source, key="duplicate", ordinal=2, title="笔记本 A", body="重复标题")
    assert import_specs([spec()]).failed == ["笔记本 A：对应 2 个评测父段"]


def test_command_reports_and_rejects_failed_file(review, tmp_path, capsys):
    path = tmp_path / "specs.json"
    path.write_text(json.dumps([spec()], ensure_ascii=False), encoding="utf-8")
    call_command("import_specs", "--file", str(path))
    assert "created=1" in capsys.readouterr().out

    path.write_text(json.dumps([spec(evidence={"cpu": "编造的引用"})], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(CommandError, match="整个文件未写库"):
        call_command("import_specs", "--file", str(path))
    assert ProductSpec.objects.get().evidence == {"battery_hours": "日常办公续航 约8小时"}
