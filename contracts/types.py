from dataclasses import dataclass, field
from datetime import date
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ImportInput:
    source_id: UUID
    build_id: UUID
    input_text: str
    title: str
    format: str
    source_type: str
    document_schema: str
    schema_version: int
    content_hash: str
    source_date: date | None
    domain_metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ContentBlock:
    kind: str
    text: str
    heading_path: list[str]
    line_start: int
    line_end: int


@dataclass(frozen=True)
class ParsedDocument:
    blocks: list[ContentBlock]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentProcessContext:
    input: ImportInput
    index_profile: dict


@dataclass(frozen=True)
class EvidenceDraft:
    ordinal: int
    body: str
    knowledge_type: str
    evidence_role: str
    context_role: str
    locator: dict
    structured_fields: dict
    warnings: list[str]


@dataclass(frozen=True)
class ContextDraft:
    ordinal: int
    title: str
    body: str
    scope_fields: dict
    field_sources: list
    locator: dict
    knowledge_types: list[str]
    warnings: list[str]
    children: list[EvidenceDraft]


@dataclass(frozen=True)
class ProcessedDocument:
    contexts: list[ContextDraft]
    warnings: list[str]


class FormatParser(Protocol):
    def parse(self, input: ImportInput) -> ParsedDocument: ...


class DocumentProcessor(Protocol):
    def process(self, document: ParsedDocument, context: DocumentProcessContext) -> ProcessedDocument: ...
