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
    def read(self, candidates, scope, top_k):
        groups = {}
        for candidate in candidates:
            groups.setdefault(candidate.context_id, []).append(candidate)
        # 父段以最佳子块的 RRF 名次排序，不因拆出更多子块而累加加权。
        parents = {parent.pk: parent for parent in scoped_contexts(scope).filter(pk__in=groups)
                   .select_related("source").prefetch_related("children")}
        results = []
        for context_id, matches in groups.items():
            parent = parents.get(context_id)
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
                "score": matches[0].score,
                "matches": [{"evidence_id": str(item.evidence_id), "score": item.score,
                             "ranks": item.ranks} for item in matches],
                "citations": [{"evidence_id": str(child.pk), "key": child.key,
                               "knowledge_type": child.knowledge_type, "locator": child.locator,
                               "metadata": child.metadata, "warnings": child.warnings}
                              for child in parent.children.all()],
            })
            if len(results) == top_k:
                break
        return results
