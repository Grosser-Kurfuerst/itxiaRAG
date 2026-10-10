"""评测指标与失败分类，只依赖结果行，供 recall_eval.py 与 compare_runs.py 共用（不需要 Django）。"""
from statistics import mean

METHODS = ("hybrid", "keyword", "vector")
SET_METRICS = ("p@5", "ndcg@5", "r@10")
SCHEMA_NAMES = {"product_review": "评测", "tutorial": "教程", "knowledge": "知识", "tool_card": "工具",
                "purchase_guide": "指南"}


def hit_metrics(ranks):
    return {"H@1": mean(r == 1 for r in ranks),
            "H@5": mean(r is not None and r <= 5 for r in ranks),
            "MRR@10": mean(1 / r if r is not None and r <= 10 else 0 for r in ranks)}


def failures(rows):
    """按（查询, 来源类别）分类：两路候选都没有答案为召回失败，召回到但未进入混合前 5 为排序失败。"""
    recall, ranking = [], []
    for r in rows:
        for schema, ranks in r.get("source_ranks", {}).items():
            tag = f"{r['id']}[{SCHEMA_NAMES.get(schema, schema)}]"
            if ranks["keyword"] is None and ranks["vector"] is None:
                recall.append(tag)
            elif ranks["hybrid"] is None or ranks["hybrid"] > 5:
                ranking.append(tag)
    return {"recall": recall, "ranking": ranking}
