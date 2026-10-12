"""规格文件导入：校验 → 关联评测父段 → 引用校验 → 差异报告 → 无失败时整体写库（方案 5.2、5.3 节）。"""
from dataclasses import dataclass, field
import json

from django.db import transaction

from catalog.models import ContextUnit
from contracts.products import ProductSpecSerializer, compact_text
from products.models import ProductSpec

REVIEW_SCHEMA = "product_review"


@dataclass
class SpecImportReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    SECTIONS = [("created", "新增"), ("updated", "更新"), ("unchanged", "未变"), ("deleted", "删除"),
                ("unlinked", "失去关联（找不到评测父段，不参与推荐）"), ("failed", "校验失败")]

    def format(self):
        lines = [" ".join(f"{name}={len(getattr(self, name))}" for name, _ in self.SECTIONS)]
        for name, label in self.SECTIONS:
            items = getattr(self, name)
            if items and name != "unchanged":
                lines += [f"{label}：", *(f"  {item}" for item in items)]
        return "\n".join(lines)


def import_specs(records, *, dry_run=False):
    """有校验失败或试运行时不写库；文件中已不存在的机型从库中删除。"""
    report = SpecImportReport()
    if not isinstance(records, list):
        report.failed.append("规格文件必须是记录列表")
        return report
    specs = _validate(records, report)
    reviews = _review_contexts([spec["key"] for spec in specs])
    existing = {spec.key: spec for spec in ProductSpec.objects.all()}
    rows = {}
    for spec in specs:
        key = spec["key"]
        matches = reviews.get(key, [])
        if len(matches) > 1:
            report.failed.append(f"{key}：对应 {len(matches)} 个评测父段")
            continue
        context = matches[0] if matches else None
        if context is None:
            report.unlinked.append(key)
        bad_quotes = _missing_quotes(spec["evidence"], context)
        if bad_quotes:
            reason = "引用不在评测正文中" if context else "没有评测父段，无法校验原文引用"
            report.failed.append(f"{key}：{reason}：{', '.join(bad_quotes)}")
            continue
        rows[key] = {**spec, "review_context_id": context.pk if context else None}
        current = existing.get(key)
        if current is None:
            report.created.append(key)
        elif any(getattr(current, name) != value for name, value in rows[key].items()):
            report.updated.append(key)
        else:
            report.unchanged.append(key)
    # 校验失败的记录仍算作文件中的机型，不报删除；与 Serializer 一样去掉 key 首尾空白。
    file_keys = {record["key"].strip() for record in records
                 if isinstance(record, dict) and isinstance(record.get("key"), str)}
    report.deleted = sorted(set(existing) - file_keys)
    if not report.failed and not dry_run:
        _write(rows, report)
    return report


def _validate(records, report):
    specs, keys = [], set()
    for number, record in enumerate(records, 1):
        if not isinstance(record, dict):
            report.failed.append(f"第 {number} 条：必须是 JSON 对象")
            continue
        label = record.get("key", f"第 {number} 条")
        serializer = ProductSpecSerializer(data=record)
        if not serializer.is_valid():
            report.failed.append(f"{label}：{json.dumps(serializer.errors, ensure_ascii=False)}")
        elif serializer.validated_data["key"] in keys:
            report.failed.append(f"{label}：key 重复")
        else:
            keys.add(serializer.validated_data["key"])
            specs.append(serializer.validated_data)
    return specs


def _review_contexts(keys):
    """按 ContextUnit.title == key 查找评测父段；调用方要求恰好 1 个。"""
    reviews = {}
    for context in ContextUnit.objects.filter(source__document_schema=REVIEW_SCHEMA, title__in=keys):
        reviews.setdefault(context.title, []).append(context)
    return reviews


def _missing_quotes(evidence, context):
    """原文引用去掉空白后必须是评测正文的子串；联网补充的引用只由人工核对。"""
    body = compact_text(context.body) if context else ""
    return [name for name, quote in evidence.items()
            if isinstance(quote, str) and compact_text(quote) not in body]


@transaction.atomic
def _write(rows, report):
    # 先删除、再更新、最后新增，避免评测父段换到另一台机型时仍被旧记录占用。
    ProductSpec.objects.filter(key__in=report.deleted).delete()
    for key in report.updated + report.created:
        ProductSpec.objects.update_or_create(key=key, defaults=rows[key])
