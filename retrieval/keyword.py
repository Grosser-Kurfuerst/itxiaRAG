"""小数据集的确定性 PostgreSQL 关键词基线。"""
import re
from dataclasses import dataclass
from uuid import UUID

from django.db.models import Case, IntegerField, Q, Value, When

from catalog.models import EvidenceUnit, ImportJob
from catalog.builds import validate_build
from catalog.selectors import published_contexts
from catalog.hashes import digest
from contracts.errors import DomainError


@dataclass(frozen=True)
class SearchScope:
    actor: object
    index_profile_hash: str
    source_ids: tuple[UUID, ...] | None = None
    knowledge_types: tuple[str, ...] | None = None

    def contexts(self):
        scope = published_contexts(self.actor, self.index_profile_hash)
        if self.source_ids is not None:
            scope = scope.filter(build__source_id__in=self.source_ids)
        if self.knowledge_types is not None:
            scope = scope.filter(knowledge_types__contained_by=list(self.knowledge_types))
        return scope

    def evidence(self):
        rows = EvidenceUnit.objects.filter(context__in=self.contexts())
        if self.knowledge_types is not None:
            rows = rows.filter(knowledge_type__in=self.knowledge_types)
        return rows


@dataclass(frozen=True)
class Candidate:
    evidence_id: UUID
    context_id: UUID
    retriever: str
    rank: int
    score: int


@dataclass(frozen=True)
class BuildSummary:
    build_id: UUID
    evidence_count: int


def terms(query, max_terms=16):
    # 点、连字符、下划线保留用于型号；纯符号不形成词项。
    pieces = re.split(r"[\s,，。?？;；!！、:：()（）\[\]【】\"“”‘’]+", query.strip())
    result, seen = [], set()
    for item in pieces:
        if not any(char.isalnum() for char in item) or item.casefold() in seen:
            continue
        seen.add(item.casefold())
        result.append(item)
    return [query.strip()] if len(result) > max_terms else result


class KeywordBackend:
    def search(self, query, scope, limit=100):
        query = query.strip()
        words = terms(query)
        if not words:
            return []
        phrase = Q(retrieval_text__icontains=query)
        match = phrase
        score = Case(When(phrase, then=Value(100)), default=Value(0), output_field=IntegerField())
        for word in words:
            condition = Q(retrieval_text__icontains=word)
            match |= condition
            score += Case(When(condition, then=Value(10)), default=Value(0), output_field=IntegerField())
            score += Case(When(context__title__icontains=word, then=Value(20)), default=Value(0), output_field=IntegerField())
        rows = (scope.evidence().filter(match).annotate(keyword_score=score)
                .order_by("-keyword_score", "id").values_list("id", "context_id", "keyword_score")[:limit])
        return [Candidate(id, context_id, "keyword", rank, value)
                for rank, (id, context_id, value) in enumerate(rows, 1)]

    def build(self, build_id, index_profile):
        job = ImportJob.objects.select_related("source").get(pk=build_id)
        if job.index_profile_hash != digest(index_profile):
            raise DomainError("PROFILE_CONFLICT", "构建配置不一致", 409)
        parents = validate_build(job)
        return BuildSummary(job.pk, sum(len(parent.children.all()) for parent in parents))
