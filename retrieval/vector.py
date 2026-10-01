"""小数据集精确余弦检索；可替换成 pgvector，保持 Retriever 协议。"""
import heapq
import math

from catalog.selectors import scoped_evidence
from contracts.types import Candidate
from embeddings.validation import validate_vectors


def cosine(left, right):
    # 先归一化再点乘，避免平方与乘积溢出。
    left_norm, right_norm = math.hypot(*left), math.hypot(*right)
    return sum((x / left_norm) * (y / right_norm) for x, y in zip(left, right))


class VectorRetriever:
    def __init__(self, embedder):
        self.embedder = embedder

    def search(self, query, scope, limit=100):
        query_vector = validate_vectors([self.embedder.embed_query(query)], 1)[0]

        def candidates():
            rows = scoped_evidence(scope).values_list("id", "context_id", "embedding")
            for evidence_id, context_id, vector in rows.iterator(chunk_size=256):
                validate_vectors([vector], 1, len(query_vector))
                yield Candidate(evidence_id, context_id, cosine(query_vector, vector))

        best = heapq.nsmallest(limit, candidates(), key=lambda item: (-item.score, str(item.evidence_id)))
        return [Candidate(item.evidence_id, item.context_id, item.score, {"vector": rank})
                for rank, item in enumerate(best, 1)]
