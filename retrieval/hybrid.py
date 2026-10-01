from contracts.types import Candidate, Ranker, Retriever


class RRFRanker:
    def __init__(self, k=60):
        if k < 1:
            raise ValueError("RRF k 必须为正数")
        self.k = k

    def rank(self, query, lists):
        merged = {}
        for candidates in lists:
            for candidate in candidates:
                item = merged.setdefault(candidate.evidence_id, candidate)
                # 每条召回路线只贡献一次；保留原始名次便于检查结果。
                ranks = dict(item.ranks)
                for name, rank in candidate.ranks.items():
                    ranks[name] = min(ranks.get(name, rank), rank)
                merged[candidate.evidence_id] = Candidate(
                    item.evidence_id, item.context_id,
                    sum(1.0 / (self.k + rank) for rank in ranks.values()), ranks)
        return sorted(merged.values(), key=lambda item: (-item.score, str(item.evidence_id)))


class HybridRetriever:
    def __init__(self, retrievers: list[Retriever], ranker: Ranker):
        self.retrievers, self.ranker = retrievers, ranker

    def search(self, query, scope, limit=100):
        lists = [retriever.search(query, scope, limit) for retriever in self.retrievers]
        return self.ranker.rank(query, lists)
