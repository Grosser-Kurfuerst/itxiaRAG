"""默认后处理步骤；候选数据与全文读取分离。"""

from contracts.types import (
    ContextBatch,
    ContextCandidate,
    EvidenceBatch,
    RouteBatch,
)
from retrieval.hybrid import RRFRanker


class RRFFusionStep:
    input_stage = "routes"
    output_stage = "evidence"

    def __init__(self, k=60, weights=None):
        self.ranker = RRFRanker(k, weights)

    def process(self, request, batch):
        if not isinstance(batch, RouteBatch):
            raise TypeError("RRFFusionStep 需要 RouteBatch")
        return EvidenceBatch(self.ranker.rank(
            request.query, list(batch.routes.values())))


class GroupParentsStep:
    input_stage = "evidence"
    output_stage = "contexts"

    def process(self, request, batch):
        if not isinstance(batch, EvidenceBatch):
            raise TypeError("GroupParentsStep 需要 EvidenceBatch")
        groups = {}
        for candidate in batch.candidates:
            groups.setdefault(candidate.context_id, []).append(candidate)
        return ContextBatch([
            ContextCandidate(context_id=context_id,
                             score=matches[0].score,
                             score_kind=matches[0].score_kind,
                             matches=matches)
            for context_id, matches in groups.items()
        ])


class TopKParentsStep:
    input_stage = "contexts"
    output_stage = "contexts"

    def process(self, request, batch):
        if not isinstance(batch, ContextBatch):
            raise TypeError("TopKParentsStep 需要 ContextBatch")
        return ContextBatch(batch.contexts[:request.top_k])
