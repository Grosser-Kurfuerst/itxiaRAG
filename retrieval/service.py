import json
import logging
from dataclasses import replace
from time import monotonic
from uuid import uuid4

from django.contrib.auth import get_user_model

from catalog.presenters import context_response
from catalog.profiles import active_profiles
from config import components
from config.runtime import require_available
from contracts.query import SearchContextSerializer
from retrieval.keyword import SearchScope
from retrieval.query_processing import QueryInput, prepare

logger = logging.getLogger(__name__)


def aggregate(candidates):
    grouped = {}
    for item in sorted(candidates, key=lambda item: item.rank):
        ids = grouped.setdefault(item.context_id, [])
        if item.evidence_id not in ids:
            ids.append(item.evidence_id)
    return grouped


def fit_contexts(items, top_k, budget):
    selected, incomplete = [], False
    size = 2  # JSON 数组的 []
    for item in items:
        if len(selected) == top_k:
            break
        encoded = json.dumps(item, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        extra = len(encoded) + bool(selected)
        if size + extra > budget:
            incomplete = True
            continue
        size += extra
        selected.append(item)
    return selected, incomplete


def search(data, actor, *, processor=None, backend=None, request_id=None):
    require_available()
    start = monotonic()
    profiles = active_profiles()
    profile = profiles.query_profile
    input = QueryInput(data["query"], data.get("scenario"), data["confirmed_context"])
    prepared = prepare(input, data["preprocess"], processor or components.query_processor(),
                       **profile["query_processing"])
    filters = data["filters"]
    scope = SearchScope(actor, profiles.index_profile_hash,
                        tuple(filters["source_ids"]) if "source_ids" in filters else None,
                        tuple(filters["knowledge_types"]) if "knowledge_types" in filters else None)
    candidates = (backend or components.keyword_backend()).search(
        prepared.retrieval_query, scope, profile["keyword"]["candidate_limit"])
    grouped = aggregate(candidates)
    parents = {parent.pk: parent for parent in scope.contexts().filter(pk__in=grouped)
               .select_related("build__source").prefetch_related("children")}
    items = [SearchContextSerializer(context_response(parents[id], ids)).data
             for id, ids in grouped.items() if id in parents]
    # 再取账号，避免 Django 的本次请求权限缓存掩盖中途撤权。
    fresh_actor = get_user_model().objects.get(pk=actor.pk)
    final_scope = replace(scope, actor=fresh_actor)
    valid = set(final_scope.contexts().filter(pk__in=grouped).values_list("id", flat=True)) if fresh_actor.is_active else set()
    invalidated = set(grouped) - valid
    valid_ids = {str(id) for id in valid}
    items = [item for item in items if item["context_id"] in valid_ids]
    contexts, incomplete = fit_contexts(items, data.get("top_k", profile["default_top_k"]),
                                        profile["response_context_bytes"])
    warnings = list(prepared.warnings)
    if invalidated:
        warnings.append("CANDIDATES_INVALIDATED")
    flags = sorted({flag for item in contexts for flag in item["flags"]})
    if incomplete:
        flags.append("context_incomplete")
    degraded = bool(warnings)
    result_status = "found" if contexts else "insufficient_evidence" if degraded or incomplete else "no_result"
    response = {
        "query_id": str(uuid4()), "index_profile_hash": profiles.index_profile_hash,
        "query_profile_hash": profiles.query_profile_hash, "feedback_available": False,
        "execution": {"status": "degraded" if degraded else "ok", "mode": "keyword", "warnings": warnings},
        "query_processing": {key: getattr(prepared, key) for key in (
            "status", "processor_id", "effective_scenario", "scenario_source", "suggested_context")},
        "result_status": result_status, "flags": flags, "missing_conditions": [], "contexts": contexts,
    }
    try:
        logger.info("search_completed", extra={
            "event": "search_completed", "request_id": request_id, "query_id": response["query_id"],
            "actor_id": actor.pk, "index_profile_hash": profiles.index_profile_hash,
            "query_profile_hash": profiles.query_profile_hash, "context_ids": [item["context_id"] for item in contexts],
            "duration_ms": round((monotonic() - start) * 1000, 2), "status": result_status})
    except Exception:
        pass  # Trace 故障不能推翻已经校验的查询结果。
    return response
