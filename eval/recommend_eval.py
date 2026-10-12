"""推荐接口评测（机型规格库方案 8.2 节 P1）：

1. 链路：D 类标准条件换算成原子条件后调用推荐服务，核对推荐集合与标注答案集合完全相同（不同说明过滤有错），并报 P@5、nDCG@5。
   nDCG@5 的理想排序含“只差一条条件”的 1 级机型，推荐结果不含这些机型，所以答案少于 5 台时 nDCG@5 小于 1。
2. 软条件排序：recommend-queries.json 中“硬条件 + 软条件”的查询，比较按 preference 排序与只按日期排序的 nDCG@5。
3. 结论附带率：全部可见机型中，结论子块取自结论栏目的比例，以及没有结论栏目、取最后一个子块兜底的篇数。

运行方式同 recall_eval.py（只读正式库，运行时挂载 eval/）：

    docker compose --env-file .env.docker -p itxia run --rm --no-deps \
      -v "$PWD/eval:/app/eval:ro" -v "$PWD/.runtime/eval:/data" -e PYTHONPATH=/app \
      app python eval/recommend_eval.py eval/queries.json eval/recommend-queries.json /data/corpus-v5/recommend-v1.json
"""
import argparse
import json
from pathlib import Path
from statistics import mean

from recall_eval import RICH_PORTS, THIN_LIGHT_MAX_KG, grades_of, load_corpus, set_metrics  # 导入时完成 django.setup()

from django.conf import settings  # noqa: E402

from catalog.models import EvidenceUnit  # noqa: E402
from config import components  # noqa: E402
from contracts.products import RecommendSerializer  # noqa: E402
from products.models import ProductSpec  # noqa: E402
from products.selectors import condition_options  # noqa: E402
from products.service import CONCLUSION_SECTIONS, recommend  # noqa: E402

VISIBILITIES = ("public", "internal")
TOP_K = 20  # 接口上限；D 类答案最多 18 台，链路检查能比较完整集合


def _oled(value):
    assert value is True, "原子条件无法表达“非 OLED”"
    return {"panel": "oled"}


# D 类标准条件 → 原子条件，口径与 recall_eval.CONSTRAINTS 一致
ATOMIC = {
    "price": lambda v: {name: x for name, x in zip(("price_min", "price_max"), v) if x is not None},
    "weight_max": lambda v: {"weight_max": v},
    "thin_light": lambda _: {"weight_max": THIN_LIGHT_MAX_KG},
    "screen_min": lambda v: {"screen_min": v},
    "battery_min": lambda v: {"battery_min": v},
    "gpu": lambda v: {"gpu_in": v},
    "ports": lambda v: {"ports": v},
    "ports_rich": lambda _: {"ports": list(RICH_PORTS)},
    "oled": _oled,
    "gaming": lambda v: {"is_gaming": v},
}


def to_conditions(constraints):
    """多条标准条件落到同一原子条件时取交集：重量上限取较小值，接口取并集。"""
    conditions = {}
    for key, value in constraints.items():
        for name, atomic in ATOMIC[key](value).items():
            if name == "weight_max" and name in conditions:
                atomic = min(atomic, conditions[name])
            elif name == "ports" and name in conditions:
                atomic = sorted(set(conditions[name]) | set(atomic))
            conditions[name] = atomic
    return conditions


class Recommender:
    def __init__(self):
        self.embedder = components.embedding_provider()
        self.collector = components.recall_collector(self.embedder)
        self.pipeline = components.post_recall_pipeline()
        self.options = condition_options(VISIBILITIES)

    def keys(self, conditions, preference=""):
        """按接口的校验规则校验请求，返回推荐机型 key 列表。"""
        serializer = RecommendSerializer(data={"conditions": conditions, "preference": preference, "top_k": TOP_K},
                                         context=self.options)
        serializer.is_valid(raise_exception=True)
        result = recommend(serializer.validated_data, VISIBILITIES, collector=self.collector, pipeline=self.pipeline,
                           embedding_space=self.embedder.space_id,
                           candidate_limit=settings.RETRIEVAL_CANDIDATE_LIMIT)
        return [product["key"] for product in result["products"]]


def chain_rows(queries, corpus, recommender):
    rows = []
    for item in queries:
        if "constraints" not in item:
            continue
        conditions = to_conditions(item["constraints"])
        grades = {corpus.contexts[cid].title: g for cid, g in grades_of(item, corpus).items()}
        order = recommender.keys(conditions)
        relevant = {title for title, g in grades.items() if g == 2}
        assert len(relevant) <= TOP_K, f"{item['id']} 答案超过 {TOP_K} 台，无法比较完整集合"
        rows.append({"id": item["id"], "q": item["q"], "conditions": conditions, "top5": order[:5],
                     "n_rel": len(relevant), "same_set": set(order) == relevant, **set_metrics(order, grades)})
    return rows


def soft_rows(queries, corpus, recommender):
    rows = []
    for item in queries:
        assert set(item["grades"]) <= set(corpus.specs), f"{item['id']} 的 grades 含规格文件中没有的机型"
        by_date = recommender.keys(item["conditions"])
        by_preference = recommender.keys(item["conditions"], item["preference"])
        rows.append({"id": item["id"], "q": item["q"], "preference": item["preference"],
                     "date": {"top5": by_date[:5], **set_metrics(by_date, item["grades"])},
                     "preference_rank": {"top5": by_preference[:5], **set_metrics(by_preference, item["grades"])}})
    return rows


def conclusion_stats():
    """统计每篇评测是否有结论栏目子块；没有的由推荐服务取最后一个子块兜底。"""
    context_ids = ProductSpec.objects.filter(review_context__source__visibility__in=VISIBILITIES) \
        .values_list("review_context_id", flat=True)
    with_conclusion = {child.context_id for child in EvidenceUnit.objects.filter(context_id__in=context_ids).only(
        "context_id", "metadata") if CONCLUSION_SECTIONS.intersection(child.metadata.get("sections", []))}
    fallback = sorted(ProductSpec.objects.filter(review_context_id__in=set(context_ids) - with_conclusion)
                      .values_list("key", flat=True))
    return {"total": len(context_ids), "with_conclusion": len(with_conclusion), "fallback": fallback}


def print_report(chain, soft, conclusions):
    print("== 链路：D 类标准条件 → 原子条件 → 推荐（按日期排序）")
    for r in chain:
        print(f"{r['id']} 答案{r['n_rel']}台 集合{'相同' if r['same_set'] else '不同'} P@5={r['p@5']:.2f} nDCG@5={r['ndcg@5']:.2f} | {r['q']} "
              f"{json.dumps(r['conditions'], ensure_ascii=False)} -> {r['top5']}")
    print(f"-- 集合相同 {sum(r['same_set'] for r in chain)}/{len(chain)} 条；平均 P@5={mean(r['p@5'] for r in chain):.3f} "
          f"nDCG@5={mean(r['ndcg@5'] for r in chain):.3f}")

    print("\n== 软条件排序：按日期 vs 按 preference（nDCG@5）")
    for r in soft:
        print(f"{r['id']} 日期={r['date']['ndcg@5']:.2f} preference={r['preference_rank']['ndcg@5']:.2f} | "
              f"{r['q']}（{r['preference']}）-> {r['preference_rank']['top5']}")
    print(f"-- 平均（n={len(soft)}）日期={mean(r['date']['ndcg@5'] for r in soft):.3f} "
          f"preference={mean(r['preference_rank']['ndcg@5'] for r in soft):.3f}")

    print(f"\n== 结论附带：{conclusions['with_conclusion']}/{conclusions['total']} 篇取自结论栏目；"
          f"兜底 {len(conclusions['fallback'])} 篇 {conclusions['fallback']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path, help="召回评测查询集（取 D 类条件查询）")
    parser.add_argument("soft", type=Path, help="软条件查询集")
    parser.add_argument("out", type=Path, help="结果 JSON 输出路径")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    soft = json.loads(args.soft.read_text(encoding="utf-8"))
    corpus = load_corpus(spec, args.spec.parent)
    recommender = Recommender()
    result = {"chain": chain_rows(spec["queries"], corpus, recommender),
              "soft": soft_rows(soft["queries"], corpus, recommender),
              "conclusions": conclusion_stats()}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print_report(**result)


if __name__ == "__main__":
    main()
