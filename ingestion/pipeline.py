"""同步应用服务：统一校验 → Embedding → 保存；不解析或划分父子段落。"""
from catalog.policies import require_permission, visible_scopes
from contracts.errors import DomainError
from contracts.serializers import SourceSerializer, validate_document
from contracts.types import DocumentStore, EmbeddingProvider, ProcessedDocument, SourceSpec
from dataclasses import asdict
from embeddings.validation import validate_vectors


def import_processed(source: SourceSpec, document: ProcessedDocument, actor, *,
                     embedder: EmbeddingProvider, store: DocumentStore):
    require_permission(actor, "maintain_source")
    serializer = SourceSerializer(data=asdict(source))
    serializer.is_valid(raise_exception=True)
    source = SourceSpec(**serializer.validated_data)
    if source.visibility not in visible_scopes(actor):
        raise DomainError("NOT_FOUND", "对象不存在", 404)
    document = validate_document(document)
    texts = [f"{parent.title}\n{child.body}" for parent in document.contexts for child in parent.children]
    vectors = validate_vectors(embedder.embed_documents(texts), len(texts))
    return store.save(source, document, vectors, embedder.space_id, actor)
