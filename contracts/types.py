"""跨模块 DTO 和变化点协议；不依赖 Django ORM 或模型厂商。"""
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol, TypeAlias
from uuid import UUID


@dataclass(frozen=True)
class EvidenceDraft:
    """retrieval_prefix 只拼入检索/编码文本（如拆分表格的表头），不属于 body 和定位。"""
    key: str
    body: str
    locator: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    retrieval_prefix: str = ""


def evidence_input(parent_title: str, body: str, prefix: str = "") -> str:
    """子块的 Embedding 与关键词检索文本；导入、保存和预算检查共用同一格式。"""
    return f"{parent_title}\n{prefix}\n{body}" if prefix else f"{parent_title}\n{body}"


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
    """连接器或原文 API 的输出；内容是字节，不接受客户端指定本机文件路径。"""
    content: bytes
    media_type: str
    metadata: dict = field(default_factory=dict)


class SourceConnector(Protocol):
    def fetch(self, locator: str) -> RawDocument: ...


class DocumentPreprocessor(Protocol):
    def process(self, raw: RawDocument) -> ProcessedDocument: ...


class PreprocessorResolver(Protocol):
    def process(self, raw: RawDocument, schema: str, version: int) -> ProcessedDocument: ...


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


@dataclass(frozen=True)
class Candidate:
    """ranks 从 1 起算；route_scores 保留原分数，score 表示当前排序分数。"""
    evidence_id: UUID
    context_id: UUID
    score: float
    ranks: dict[str, int] = field(default_factory=dict)
    route_scores: dict[str, float] = field(default_factory=dict)
    score_kind: str = "raw"


class Retriever(Protocol):
    name: str

    def search(self, query: str, scope: SearchScope, limit: int) -> list[Candidate]: ...


@dataclass(frozen=True)
class SearchRequest:
    query: str
    scope: SearchScope
    top_k: int


@dataclass(frozen=True)
class RouteBatch:
    routes: dict[str, list[Candidate]]


@dataclass(frozen=True)
class EvidenceBatch:
    candidates: list[Candidate]


@dataclass(frozen=True)
class ContextCandidate:
    context_id: UUID
    score: float
    score_kind: str
    matches: list[Candidate]


@dataclass(frozen=True)
class ContextBatch:
    contexts: list[ContextCandidate]


SearchBatch: TypeAlias = RouteBatch | EvidenceBatch | ContextBatch
SearchStage: TypeAlias = Literal["routes", "evidence", "contexts"]


class RecallCollector(Protocol):
    def collect(self, query: str, scope: SearchScope, limit: int) -> RouteBatch: ...


class SearchStep(Protocol):
    input_stage: SearchStage
    output_stage: SearchStage

    def process(self, request: SearchRequest, batch: SearchBatch) -> SearchBatch: ...


class SearchPipeline(Protocol):
    def run(self, request: SearchRequest, routes: RouteBatch) -> ContextBatch: ...


class Ranker(Protocol):
    def rank(self, query: str, lists: list[list[Candidate]]) -> list[Candidate]: ...


class ContextReader(Protocol):
    def read(self, contexts: list[ContextCandidate], scope: SearchScope) -> list[dict]: ...
