from contracts.types import Candidate, Retriever, RouteBatch


class MultiRouteRecall:
    """按固定顺序收集各召回路线，后续处理由 PostRecallPipeline 负责。"""

    def __init__(self, retrievers: list[Retriever]):
        self.retrievers = tuple(retrievers)
        names = [retriever.name for retriever in self.retrievers]
        if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
            raise ValueError("每条召回路线必须有唯一 name")

    def collect(self, query, scope, limit):
        return RouteBatch({retriever.name: retriever.search(query, scope, limit)
                           for retriever in self.retrievers})


class RRFRanker:
    def __init__(self, k=60):
        if k < 1:
            raise ValueError("RRF k 必须为正数")
        self.k = k

    def rank(self, query, lists):
        merged = {}
        for candidates in lists:
            for candidate in candidates:
                item = merged.get(candidate.evidence_id)
                ranks = dict(item.ranks) if item else {}
                scores = dict(item.route_scores) if item else {}
                # 同一路线只贡献最佳名次，并保留该名次对应的原始分数。
                for name, rank in candidate.ranks.items():
                    if name not in ranks or rank < ranks[name]:
                        ranks[name] = rank
                        scores[name] = candidate.route_scores.get(name, candidate.score)
                merged[candidate.evidence_id] = Candidate(
                    candidate.evidence_id, candidate.context_id,
                    sum(1.0 / (self.k + rank) for rank in ranks.values()), ranks, scores, "rrf")
        return sorted(merged.values(), key=lambda item: (-item.score, str(item.evidence_id)))
