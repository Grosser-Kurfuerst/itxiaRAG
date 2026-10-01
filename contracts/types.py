"""跨模块 DTO 和变化点协议；不依赖 Django ORM 或模型厂商。"""
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class EvidenceDraft:
    key: str
    body: str
    knowledge_type: str = "concept"
    locator: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContextDraft:
    key: str
    title: str
    body: str
    children: list[EvidenceDraft]
    locator: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProcessedDocument:
    title: str
    document_schema: str
    contexts: list[ContextDraft]
    schema_version: int = 1
    source_date: date | None = None
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SourceSpec:
    source_type: str
    canonical_locator: str
    visibility: str
    source_url: str | None = None


@dataclass(frozen=True)
class RawDocument:
    """未来连接器的输出；不接受客户端指定文件路径或可执行插件路径。"""
    content: bytes
    media_type: str
    metadata: dict = field(default_factory=dict)


class SourceConnector(Protocol):
    def fetch(self, locator: str) -> RawDocument: ...


class DocumentPreprocessor(Protocol):
    def process(self, raw: RawDocument) -> ProcessedDocument: ...


@dataclass(frozen=True)
class ImportResult:
    source_id: UUID
    context_ids: list[UUID]
    reused: bool


class DocumentStore(Protocol):
    def save(self, source: SourceSpec, document: ProcessedDocument,
             vectors: list[list[float]], embedding_space: str, actor: object) -> ImportResult: ...


class EmbeddingProvider(Protocol):
    @property
    def space_id(self) -> str: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class SearchScope:
    visibilities: tuple[str, ...]
    embedding_space: str
    source_ids: tuple[UUID, ...] | None = None
    knowledge_types: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Candidate:
    """ranks 使用唯一召回路线名，名次从 1 起算；召回器输出必须包含自身路线。"""
    evidence_id: UUID
    context_id: UUID
    score: float
    ranks: dict[str, int] = field(default_factory=dict)


class Retriever(Protocol):
    def search(self, query: str, scope: SearchScope, limit: int) -> list[Candidate]: ...


class Ranker(Protocol):
    def rank(self, query: str, lists: list[list[Candidate]]) -> list[Candidate]: ...


class ContextReader(Protocol):
    def read(self, candidates: list[Candidate], scope: SearchScope, top_k: int) -> list[dict]: ...
