"""按条件推荐机型（方案 6.2 节）：硬条件过滤 → 按 preference 在候选评测中排序 → 附结论与命中子块。

召回器与后处理流水线由调用方注入，这里不直接依赖 retrieval。
"""
from dataclasses import replace
from datetime import date

from catalog.models import EvidenceUnit
from catalog.selectors import scoped_contexts
from contracts.types import SearchRequest, SearchScope
from products.conditions import diagnostics, match, unknown_counts
from products.models import ProductSpec

CONCLUSION_SECTIONS = {"总结", "结论", "优缺点", "优点", "缺点", "购买建议", "推荐理由", "不推荐理由", "猪王的良心结语"}
MAX_CONCLUSIONS = 3
MAX_HIGHLIGHTS = 2
# 规格卡返回的字段：去掉身份、关联和只供维护核对的引用。
SPEC_FIELDS = [field.name for field in ProductSpec._meta.fields
               if field.name not in {"id", "key", "review_context", "evidence", "updated_at"}]


def recommend(data, visibilities, *, collector, pipeline, embedding_space, candidate_limit=100):
    scope = SearchScope(tuple(visibilities), embedding_space)
    specs = list(ProductSpec.objects.filter(review_context__in=scoped_contexts(scope))
                 .select_related("review_context__source").defer("review_context__body"))
    conditions = data["conditions"]
    candidates = match(specs, conditions)
    result = {"result_status": "found" if candidates else "no_result", "products": [],
              "unknown": unknown_counts(specs, conditions), "diagnostics": None}
    if not candidates:
        result["diagnostics"] = diagnostics(specs, conditions)
        return result
    hits = _preference_hits(data.get("preference", ""), candidates, scope, collector, pipeline, candidate_limit)
    ranked = rank(candidates, hits)[:data["top_k"]]
    children = _children([spec.review_context_id for spec in ranked])
    result["products"] = [_product(spec, children[spec.review_context_id], hits.get(spec.review_context_id, []))
                          for spec in ranked]
    return result


def _preference_hits(preference, candidates, scope, collector, pipeline, candidate_limit):
    """在候选机型的评测父段中检索 preference，返回 {父段 id: 命中子块}，按名次排列。"""
    if not preference.strip():
        return {}
    scope = replace(scope, context_ids=tuple(spec.review_context_id for spec in candidates))
    request = SearchRequest(preference, scope, len(candidates))
    batch = pipeline.run(request, collector.collect(preference, scope, candidate_limit))
    return {context.context_id: context.matches for context in batch.contexts}


def rank(candidates, hits):
    """有软条件命中的按名次在前；其余按评测日期由新到旧，同日按 key。"""
    by_date = sorted(candidates, key=lambda spec: spec.key)
    by_date.sort(key=lambda spec: spec.review_context.source.source_date or date.min, reverse=True)
    order = {context_id: number for number, context_id in enumerate(hits)}
    return sorted(by_date, key=lambda spec: order.get(spec.review_context_id, len(order)))


def conclusions(children):
    """每个结论栏目取第一个子块，最多 3 个，按原文顺序；没有结论栏目时取最后一个子块。"""
    picked, seen = [], set()
    for child in children:
        sections = CONCLUSION_SECTIONS.intersection(child.metadata.get("sections", []))
        if sections - seen:
            picked.append(child)
            seen |= sections
    return picked[:MAX_CONCLUSIONS] or children[-1:]


def _children(context_ids):
    children = {context_id: [] for context_id in context_ids}
    for child in EvidenceUnit.objects.filter(context_id__in=context_ids).only("id", "context_id", "key", "body", "metadata"):
        children[child.context_id].append(child)
    return children


def _evidence(child):
    return {"evidence_id": str(child.pk), "key": child.key, "sections": child.metadata.get("sections", []),
            "text": child.body}


def _product(spec, children, matches):
    context, by_id = spec.review_context, {child.pk: child for child in children}
    source = context.source
    highlights = [{**_evidence(by_id[item.evidence_id]), "score": item.score}
                  for item in matches if item.evidence_id in by_id][:MAX_HIGHLIGHTS]
    return {
        "key": spec.key,
        "spec": {name: getattr(spec, name) for name in SPEC_FIELDS},
        "review": {"context_id": str(context.pk), "title": context.title,
                   "source": {"id": str(source.pk), "title": source.title, "url": source.source_url, "source_date": source.source_date},
                   "conclusions": [_evidence(child) for child in conclusions(children)],
                   "highlights": highlights},
    }
