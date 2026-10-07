from catalog.models import ContextUnit, EvidenceUnit


def scoped_contexts(scope):
    rows = ContextUnit.objects.filter(source__visibility__in=scope.visibilities,
                                      source__embedding_space=scope.embedding_space)
    if scope.source_ids is not None:
        rows = rows.filter(source_id__in=scope.source_ids)
    return rows


def scoped_evidence(scope):
    rows = EvidenceUnit.objects.filter(context__in=scoped_contexts(scope))
    if scope.knowledge_types is not None:
        rows = rows.filter(knowledge_type__in=scope.knowledge_types)
    return rows


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
