"""同步导入应用服务；原文先交给注册预处理器，标准文档走统一编码/保存。

权限只在调用入口检查：HTTP 接口要求 maintain_source，命令行由能进入部署环境的维护者执行。
"""
from contracts.serializers import SourceSerializer, validate_document
from contracts.types import (
    DocumentStore, EmbeddingProvider, PreprocessorResolver, ProcessedDocument, RawDocument, SourceSpec, evidence_input,
)
from dataclasses import asdict
from embeddings.validation import validate_vectors


def _validate_source(source: SourceSpec) -> SourceSpec:
    serializer = SourceSerializer(data=asdict(source))
    serializer.is_valid(raise_exception=True)
    return SourceSpec(**serializer.validated_data)


def import_processed(source: SourceSpec, document: ProcessedDocument, *,
                     embedder: EmbeddingProvider, store: DocumentStore):
    source = _validate_source(source)
    document = validate_document(document)
    unchanged = store.find_unchanged(source, document, embedder.space_id)
    if unchanged:
        return unchanged
    texts = [evidence_input(parent.title, child.body, child.retrieval_prefix)
             for parent in document.contexts for child in parent.children]
    vectors = validate_vectors(embedder.embed_documents(texts), len(texts))
    return store.save(source, document, vectors, embedder.space_id)


def import_raw(source: SourceSpec, raw: RawDocument, schema: str, version: int, *,
               registry: PreprocessorResolver, embedder: EmbeddingProvider, store: DocumentStore):
    """原文入口只负责接线；解析、分段和长度控制留在注册的预处理器。"""
    document = preprocess_raw(source, raw, schema, version, registry=registry)
    return import_processed(source, document, embedder=embedder, store=store)


def preprocess_raw(source: SourceSpec, raw: RawDocument, schema: str, version: int, *,
                   registry: PreprocessorResolver) -> ProcessedDocument:
    """先校验来源，再处理原文；失败不触发 Embedding。"""
    _validate_source(source)
    return registry.process(raw, schema, version)
