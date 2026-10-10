from django.db.models import CharField, Value
from django.db.models.functions import Concat

from catalog.models import ContextUnit, EvidenceUnit

# 来源类型 + 定位符唯一确定来源，父段、子块 key 在来源内唯一；拼接结果重新导入后不变。
EVIDENCE_STABLE_KEY = Concat(
    "context__source__source_type", Value(":"), "context__source__canonical_locator",
    Value("#"), "context__key", Value("#"), "key", output_field=CharField())


def scoped_contexts(scope):
    rows = ContextUnit.objects.filter(source__visibility__in=scope.visibilities,
                                      source__embedding_space=scope.embedding_space)
    if scope.source_ids is not None:
        rows = rows.filter(source_id__in=scope.source_ids)
    return rows


def scoped_evidence(scope):
    return EvidenceUnit.objects.filter(context__in=scoped_contexts(scope)).annotate(stable_key=EVIDENCE_STABLE_KEY)


class DjangoContextReader:
    def read(self, contexts, scope):
        parents = {parent.pk: parent for parent in scoped_contexts(scope).filter(
                   pk__in=[item.context_id for item in contexts])
                   .select_related("source")}
        evidence_ids = {
            item.evidence_id
            for context in contexts
            for item in context.matches
        }
        evidence = {
            row.pk: row
            for row in EvidenceUnit.objects.filter(
                context_id__in=parents, pk__in=evidence_ids,
            ).only("id", "context_id", "key", "locator")
        }
        results = []
        for context in contexts:
            parent = parents.get(context.context_id)
            if parent is None:
                continue
            source = parent.source
            results.append({
                "context_id": str(parent.pk), "key": parent.key, "title": parent.title, "text": parent.body,
                "locator": parent.locator, "metadata": parent.metadata,
                "warnings": source.warnings + parent.warnings,
                "source": {"id": str(source.pk), "title": source.title, "url": source.source_url,
                           "source_type": source.source_type, "source_date": source.source_date,
                           "document_schema": source.document_schema, "schema_version": source.schema_version},
                "score": context.score,
                "score_kind": context.score_kind,
                "matches": [{"evidence_id": str(item.evidence_id), "score": item.score,
                             "score_kind": item.score_kind, "route_scores": item.route_scores,
                             "ranks": item.ranks, "key": evidence[item.evidence_id].key,
                             "locator": evidence[item.evidence_id].locator}
                            for item in context.matches if item.evidence_id in evidence
                            and evidence[item.evidence_id].context_id == parent.pk],
            })
        return results
