"""同步导入应用服务；原文先交给注册预处理器，标准文档走统一编码/保存。"""
from catalog.policies import require_permission, visible_scopes
from contracts.errors import DomainError
from contracts.serializers import SourceSerializer, validate_document
from contracts.types import (
    DocumentStore, EmbeddingProvider, PreprocessorResolver, ProcessedDocument, RawDocument, SourceSpec, evidence_input,
)
from dataclasses import asdict
from embeddings.validation import validate_vectors


def _validate_source(source: SourceSpec, actor) -> SourceSpec:
    require_permission(actor, "maintain_source")
    serializer = SourceSerializer(data=asdict(source))
    serializer.is_valid(raise_exception=True)
    source = SourceSpec(**serializer.validated_data)
    if source.visibility not in visible_scopes(actor):
        raise DomainError("NOT_FOUND", "对象不存在", 404)
    return source


def import_processed(source: SourceSpec, document: ProcessedDocument, actor, *,
                     embedder: EmbeddingProvider, store: DocumentStore):
    source = _validate_source(source, actor)
    document = validate_document(document)
    texts = [evidence_input(parent.title, child.body, child.retrieval_prefix)
             for parent in document.contexts for child in parent.children]
    vectors = validate_vectors(embedder.embed_documents(texts), len(texts))
    return store.save(source, document, vectors, embedder.space_id, actor)


def import_raw(source: SourceSpec, raw: RawDocument, schema: str, version: int, actor, *,
               registry: PreprocessorResolver, embedder: EmbeddingProvider, store: DocumentStore):
    """原文入口只负责接线；解析、分段和长度控制留在注册的预处理器。"""
    document = preprocess_raw(source, raw, schema, version, actor, registry=registry)
    return import_processed(source, document, actor, embedder=embedder, store=store)


def preprocess_raw(source: SourceSpec, raw: RawDocument, schema: str, version: int, actor, *,
                   registry: PreprocessorResolver) -> ProcessedDocument:
    """先校验动作权限/来源范围，再处理原文；失败不触发 Embedding。"""
    _validate_source(source, actor)
    return registry.process(raw, schema, version)
