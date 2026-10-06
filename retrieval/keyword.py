"""先按 SearchScope 过滤，再对可见子块分词并计算 BM25。"""
import heapq
import math
from dataclasses import replace

from catalog.selectors import scoped_evidence
from contracts.types import Candidate
from retrieval.bm25 import bm25_scores
from retrieval.tokenization import tokenize


class KeywordRetriever:
    name = "keyword"

    def __init__(self, tokenizer=tokenize, min_bm25=0.0):
        if not math.isfinite(min_bm25) or min_bm25 < 0:
            raise ValueError("min_bm25 必须为非负有限数值")
        self.tokenize = tokenizer
        self.min_bm25 = min_bm25

    def search(self, query, scope, limit=100):
        words = self.tokenize(query)
        if not words:
            return []
        rows = list(scoped_evidence(scope).values_list("id", "context_id", "retrieval_text"))
        scores = bm25_scores([self.tokenize(text) for _, _, text in rows], words)
        candidates = [Candidate(evidence_id, context_id, score,
                                route_scores={self.name: score}, score_kind="bm25")
                      for (evidence_id, context_id, _), score in zip(rows, scores)
                      if score > 0 and score >= self.min_bm25]
        best = heapq.nsmallest(limit, candidates, key=lambda item: (-item.score, str(item.evidence_id)))
        return [replace(item, ranks={self.name: rank})
                for rank, item in enumerate(best, 1)]
