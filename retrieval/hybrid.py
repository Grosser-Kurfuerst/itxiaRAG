import math

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
    """加权 RRF：得分为各路线 weight / (k + 名次) 之和；未配置权重的路线按 1 计。"""

    def __init__(self, k=60, weights=None):
        if k < 1:
            raise ValueError("RRF k 必须为正数")
        self.weights = dict(weights or {})
        if any(not math.isfinite(w) or w <= 0 for w in self.weights.values()):
            raise ValueError("RRF 路线权重必须为正的有限数值")
        self.k = k

    def weight(self, route):
        return self.weights.get(route, 1.0)

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
                score = sum(self.weight(name) / (self.k + rank) for name, rank in ranks.items())
                merged[candidate.evidence_id] = Candidate(
                    candidate.evidence_id, candidate.context_id, score, ranks, scores, "rrf",
                    candidate.stable_key)
        return sorted(merged.values(), key=Candidate.sort_key)
