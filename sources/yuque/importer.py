"""语雀批量导入编排；边界校验与原文 API 共用同一契约。"""
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ValidationError

from contracts.errors import DomainError
from contracts.serializers import RawSourceImportSerializer, import_raw_dtos
from contracts.types import ImportResult, ProcessedDocument
from sources.yuque.client import YuqueClient, YuqueDocRef
from sources.yuque.manifest import Classification, Manifest


def clean_title(title: str) -> str:
    title = re.sub(r"^(?:【[^】]*】\s*)+", "", title.strip())
    title = re.sub(r"^[^|｜]{0,20}[|｜]\s*", "", title)
    return re.sub(r"[\s⭐]+$", "", title).strip()


def build_request(ref: YuqueDocRef, markdown: str, manifest: Manifest, *,
                  schema: str, version: int, classification: Classification | None = None) -> dict:
    classification = classification or manifest.classify(ref)
    return {
        "source": {
            "source_type": "yuque",
            "canonical_locator": f"doc:{ref.doc_id}",
            "visibility": manifest.visibility_for(ref),
            "source_url": f"https://www.yuque.com/{manifest.group}/{ref.book}/{ref.slug}",
        },
        "preprocess": {"schema": schema, "version": version},
        "raw": {
            "content": markdown,
            "media_type": "text/x-yuque-markdown",
            "metadata": {
                "title": clean_title(ref.title),
                "source_date": ref.content_updated_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                "collection_path": list(ref.toc_path),
                "yuque": {
                    "doc_id": ref.doc_id, "book": ref.book, "slug": ref.slug,
                    "title_raw": ref.title, "content_updated_at": ref.content_updated_at.isoformat(),
                    "classified_by": classification.decided_by,
                },
            },
        },
    }


@dataclass(frozen=True)
class SubmissionResult:
    """保留预处理统计，不改变公共 ImportResult；result 为空表示试运行。"""
    document: ProcessedDocument
    result: ImportResult | None = None


@dataclass(frozen=True)
class ImportRow:
    doc: str
    classification: Classification
    status: str
    parents: int | None = None
    children: int | None = None
    detail: str = ""


@dataclass
class ImportReport:
    rows: list[ImportRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        counts = Counter(row.status for row in self.rows)
        return {status: counts[status] for status in
                ("imported", "reused", "preprocessed", "skipped", "unregistered", "failed")}

    def format(self) -> str:
        table = [["doc", "category(by)", "status", "parents", "children", "detail"]]
        for row in self.rows:
            classification = row.classification
            category = classification.category or "-"
            if classification.decided_by != "none":
                category += f"({classification.decided_by})"
            table.append([row.doc, category, row.status,
                          str(row.parents) if row.parents is not None else "-",
                          str(row.children) if row.children is not None else "-", row.detail])
        # 警告可以含换行；每篇报告保持一行，也不输出正文。
        table = [[" ".join(cell.splitlines()) for cell in row] for row in table]
        widths = [max(len(row[index]) for row in table) for index in range(5)]
        lines = ["  ".join(cell.ljust(width) for cell, width in zip(row[:5], widths)) + "  " + row[5]
                 for row in table]
        lines.extend(f"warning: {warning}" for warning in self.warnings)
        lines.append("summary: " + " ".join(f"{key}={value}" for key, value in self.summary.items()))
        return "\n".join(line.rstrip() for line in lines)


class YuqueImportService:
    def __init__(self, client: YuqueClient, manifest: Manifest,
                 category_pipelines: Mapping[str, tuple[str, int]], submit):
        self.client, self.manifest = client, manifest
        self.category_pipelines, self.submit = category_pipelines, submit

    def run(self, refs: Iterable[YuqueDocRef], *, only: Iterable[str] | None = None,
            read_errors: Mapping[str, DomainError] | None = None) -> ImportReport:
        refs = list(refs)
        selected = set(only) if only else None
        available = {f"{ref.book}/{ref.slug}" for ref in refs}
        expected = selected if selected is not None else self.manifest.docs.keys()
        report = ImportReport(warnings=[
            f"{key} 在文档列表中找不到，slug 可能已改名，请核对清单"
            for key in sorted(set(expected) - available)
        ])
        for ref in refs:
            key = f"{ref.book}/{ref.slug}"
            classification = self.manifest.classify(ref)
            if read_errors and key in read_errors:
                exc = read_errors[key]
                report.rows.append(ImportRow(key, classification, "failed", detail=f"{exc.code}: {exc.message}"))
                continue
            if selected is not None and key not in selected:
                continue
            if classification.skip:
                detail = classification.skip
                canonical = self.manifest.canonical_for(ref)
                if canonical:
                    detail += f" → {canonical}"
                report.rows.append(ImportRow(key, classification, "skipped", detail=detail))
                continue
            if classification.category is None:
                report.rows.append(ImportRow(key, classification, "unregistered", detail="请在清单中登记类别或 skip"))
                continue
            if classification.category not in self.category_pipelines:
                report.rows.append(ImportRow(key, classification, "skipped", detail="未接入"))
                continue
            schema, version = self.category_pipelines[classification.category]
            try:
                request = build_request(ref, self.client.read_markdown(ref), self.manifest,
                                        schema=schema, version=version, classification=classification)
                serializer = RawSourceImportSerializer(data=request)
                serializer.is_valid(raise_exception=True)
                submitted = self.submit(*import_raw_dtos(serializer.validated_data))
                document, result = submitted.document, submitted.result
                status = "preprocessed" if result is None else "reused" if result.reused else "imported"
                warnings = [
                    *document.warnings,
                    *(warning for parent in document.contexts for warning in parent.warnings),
                    *(warning for parent in document.contexts for child in parent.children
                      for warning in child.warnings),
                ]
                report.rows.append(ImportRow(
                    key, classification, status, len(document.contexts),
                    sum(len(parent.children) for parent in document.contexts),
                    "；".join(warning if len(warning) <= 30 else warning[:30] + "…"
                             for warning in dict.fromkeys(warnings)),
                ))
            except DomainError as exc:
                report.rows.append(ImportRow(key, classification, "failed", detail=f"{exc.code}: {exc.message}"))
            except ValidationError as exc:
                report.rows.append(ImportRow(key, classification, "failed",
                                            detail=f"INVALID_REQUEST: {exc.get_codes()}"))
        return report
