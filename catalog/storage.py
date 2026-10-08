"""PostgreSQL 保存适配器；稳定 key 更新同一父段/子块，无构建和发布流程。"""
from dataclasses import asdict
import hashlib
import json

from django.db import transaction

from catalog.models import ContextUnit, EvidenceUnit, KnowledgeSource
from catalog.policies import require_permission, visible_scopes
from contracts.errors import DomainError
from contracts.types import ImportResult, evidence_input
from embeddings.validation import validate_vectors


def content_hash(source, document):
    content = {"source": asdict(source), "document": asdict(document)}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                    default=str, allow_nan=False).encode()).hexdigest()


class DjangoDocumentStore:
    @transaction.atomic
    def save(self, source_spec, document, vectors, embedding_space, actor):
        require_permission(actor, "maintain_source")
        if source_spec.visibility not in visible_scopes(actor):
            raise DomainError("NOT_FOUND", "对象不存在", 404)
        validate_vectors(vectors, sum(len(c.children) for c in document.contexts))
        digest = content_hash(source_spec, document)
        fields = {key: value for key, value in asdict(document).items() if key != "contexts"}
        fields.update(source_url=source_spec.source_url, visibility=source_spec.visibility,
                      content_hash=digest, embedding_space=embedding_space)
        source, _ = KnowledgeSource.objects.get_or_create(
            source_type=source_spec.source_type, canonical_locator=source_spec.canonical_locator,
            defaults=fields)
        source = KnowledgeSource.objects.select_for_update().get(pk=source.pk)
        if source.visibility not in visible_scopes(actor):
            raise DomainError("NOT_FOUND", "对象不存在", 404)
        if source.content_hash == digest and source.embedding_space == embedding_space and source.contexts.exists():
            return ImportResult(source.pk, list(source.contexts.values_list("id", flat=True)), True)
        for name, value in fields.items():
            setattr(source, name, value)
        source.save()
        vector_iter, context_ids = iter(vectors), []
        for ordinal, parent in enumerate(document.contexts, 1):
            parent_fields = {name: value for name, value in asdict(parent).items() if name not in {"key", "children"}}
            context, _ = ContextUnit.objects.update_or_create(
                source=source, key=parent.key, defaults={**parent_fields, "ordinal": ordinal})
            context_ids.append(context.pk)
            child_keys = []
            for child_ordinal, child in enumerate(parent.children, 1):
                child_fields = asdict(child)
                child_keys.append(child_fields.pop("key"))
                prefix = child_fields.pop("retrieval_prefix")
                EvidenceUnit.objects.update_or_create(context=context, key=child.key, defaults={
                    **child_fields, "ordinal": child_ordinal,
                    "retrieval_text": evidence_input(parent.title, child.body, prefix),
                    "embedding": next(vector_iter)})
            context.children.exclude(key__in=child_keys).delete()
        source.contexts.exclude(pk__in=context_ids).delete()
        return ImportResult(source.pk, context_ids, False)
