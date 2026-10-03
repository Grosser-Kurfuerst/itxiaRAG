"""先按 SearchScope 过滤，再对可见子块分词并计算 BM25。"""
import heapq

from catalog.selectors import scoped_evidence
from contracts.types import Candidate
from retrieval.bm25 import bm25_scores
from retrieval.tokenization import tokenize


class KeywordRetriever:
    name = "keyword"

    def __init__(self, tokenizer=tokenize):
        self.tokenize = tokenizer

    def search(self, query, scope, limit=100):
        words = self.tokenize(query)
        if not words:
            return []
        rows = list(scoped_evidence(scope).values_list("id", "context_id", "retrieval_text"))
        scores = bm25_scores([self.tokenize(text) for _, _, text in rows], words)
        candidates = [Candidate(evidence_id, context_id, score)
                      for (evidence_id, context_id, _), score in zip(rows, scores) if score > 0]
        best = heapq.nsmallest(limit, candidates, key=lambda item: (-item.score, str(item.evidence_id)))
        return [Candidate(item.evidence_id, item.context_id, item.score, {self.name: rank})
                for rank, item in enumerate(best, 1)]
