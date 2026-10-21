"""评测指标与失败分类，只依赖结果行，供 recall_eval.py 与 compare_runs.py 共用（不需要 Django）。"""
import math
from statistics import mean

from cases import contains

METHODS = ("hybrid", "keyword", "vector")
METRIC_VERSION = "strict-v2"
SET_METRICS = ("precision", "ndcg@5", "recall@10")
SCHEMA_NAMES = {"product_review": "评测", "tutorial": "教程", "knowledge": "知识", "tool_card": "工具",
                "purchase_guide": "指南", "troubleshooting": "排障", "experience_case": "案例"}


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


def set_metrics(order, grades):
    """精确率按实际返回数；Recall@10 按全部严格相关答案数；空正例不算召回。"""
    order = list(dict.fromkeys(order))
    relevant = {cid for cid, grade in grades.items() if grade == 2}
    dcg = sum((2 ** grades.get(cid, 0) - 1) / math.log2(i + 2) for i, cid in enumerate(order[:5]))
    ideal = sorted(grades.values(), reverse=True)[:5]
    idcg = sum((2 ** grade - 1) / math.log2(i + 2) for i, grade in enumerate(ideal))
    return {"precision": sum(cid in relevant for cid in order) / len(order) if order else 0.0,
            "ndcg@5": dcg / idcg if idcg else 0.0,
            "recall@10": sum(cid in relevant for cid in order[:10]) / len(relevant) if relevant else None,
            "returned": len(order)}


def need_coverage(needs, order, bodies, aliases, k=5):
    """必要需求之间 AND，同需求证据之间 OR；按返回父段正文核实。"""
    top = set(order[:k])
    covered = {n["id"]: any(cid in top and contains(bodies[cid], e["quote"])
                            for e in n.get("evidence", []) for cid in aliases[e["ref"]]) for n in needs}
    return {"covered": covered, "all": all(covered.values()),
            "fraction": sum(covered.values()) / len(covered) if covered else None}


def average_sets(rows, method):
    return {"n": len(rows), **{key: mean(values) if (values := [r["set"][method][key] for r in rows
                                                               if r["set"][method][key] is not None]) else None
                               for key in SET_METRICS}}
