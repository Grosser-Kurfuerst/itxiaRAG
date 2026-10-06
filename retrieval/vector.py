"""小数据集精确余弦检索；可替换成 pgvector，保持 Retriever 协议。"""
import heapq
import math
from dataclasses import replace

from catalog.selectors import scoped_evidence
from contracts.types import Candidate
from embeddings.validation import validate_vectors


def cosine(left, right):
    # 先归一化再点乘，避免平方与乘积溢出。
    left_norm, right_norm = math.hypot(*left), math.hypot(*right)
    score = sum((x / left_norm) * (y / right_norm) for x, y in zip(left, right))
    # 将浮点误差内的同向／反向结果归到端点，保持 ±1 闭区间门槛的语义。
    if math.isclose(abs(score), 1.0, rel_tol=0.0, abs_tol=1e-12):
        return math.copysign(1.0, score)
    return score


class VectorRetriever:
    name = "vector"

    def __init__(self, embedder, min_cosine=None):
        if min_cosine is not None and (not math.isfinite(min_cosine) or not -1 <= min_cosine <= 1):
            raise ValueError("min_cosine 必须为 [-1, 1] 内的有限数值")
        self.embedder = embedder
        self.min_cosine = min_cosine

    def search(self, query, scope, limit=100):
        query_vector = validate_vectors([self.embedder.embed_query(query)], 1)[0]

        def candidates():
            rows = scoped_evidence(scope).values_list("id", "context_id", "embedding")
            for evidence_id, context_id, vector in rows.iterator(chunk_size=256):
                validate_vectors([vector], 1, len(query_vector))
                score = cosine(query_vector, vector)
                if self.min_cosine is None or score >= self.min_cosine:
                    yield Candidate(evidence_id, context_id, score,
                                    route_scores={self.name: score}, score_kind="cosine")

        best = heapq.nsmallest(limit, candidates(), key=lambda item: (-item.score, str(item.evidence_id)))
        return [replace(item, ranks={self.name: rank})
                for rank, item in enumerate(best, 1)]
