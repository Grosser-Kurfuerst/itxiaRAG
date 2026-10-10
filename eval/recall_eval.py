"""初步召回评测：父段级 Hit/MRR、分路排名、事实子块排名、负例分数；
D 类按属性条件生成分级标注，另报 P@5、nDCG@5、R@10。

答案按来源类别分别报三路名次，区分召回失败（两路候选中都没有）与排序失败（已召回但未进入混合前 5）。
查询集的 scopes 定义若干检索范围（范围名 -> document_schema 列表），每个范围各跑一遍；
答案按范围过滤，范围内没有答案的查询在该范围按负例统计。
别名可指向评测标题（字符串），或指向语雀文档的父段 {"doc": "book/slug", "titles": [...]}，省略 titles 表示整篇。

查询集 queries.json 与属性表 attributes.json 在本目录；语料原文与评测结果放在被忽略的 .runtime/eval/。
镜像不含本目录，运行时挂载：

    docker compose --env-file .env.docker -p itxia run --rm --no-deps [-e POSTGRES_DB=itxia_eval] \
      -v "$PWD/eval:/app/eval:ro" -v "$PWD/.runtime/eval:/data" -e PYTHONPATH=/app \
      app python eval/recall_eval.py eval/queries.json /data/corpus-v2/results-v4.json
"""
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from catalog.models import ContextUnit, EvidenceUnit, KnowledgeSource  # noqa: E402
from config import components  # noqa: E402
from contracts.types import SearchRequest, SearchScope  # noqa: E402

METHODS = ("hybrid", "keyword", "vector")
SET_METRICS = ("p@5", "ndcg@5", "r@10")
CANDIDATES_PER_ROUTE = 100
TOP_PARENTS = 20
RICH_PORTS = ("usb_a", "usb_c", "video_out")  # 视频输出含 HDMI、DP 与支持 DP 的 USB-C；网口不作要求
THIN_LIGHT_MAX_KG = 1.5
DEFAULT_SCOPES = {"reviews": ["product_review"]}
SCHEMA_NAMES = {"product_review": "评测", "tutorial": "教程", "purchase_guide": "指南"}


@dataclass
class Corpus:
    contexts: dict    # 父段 id -> ContextUnit
    evidence: dict    # 子块 id -> (父段 id, 正文)
    alias_ctx: dict   # 查询集别名 -> 父段 id 元组
    title_ctx: dict   # 评测标题 -> 父段 id
    attributes: dict  # 评测标题 -> 机型属性

    def label(self, context_id):
        for alias, ids in self.alias_ctx.items():
            if context_id in ids:
                return alias
        c = self.contexts[context_id]
        prefix = {"purchase_guide": "指南:", "tutorial": "语雀:"}.get(c.source.document_schema, "")
        return prefix + c.title.split(" > ")[-1][:16]

    def schema_of(self, context_id):
        return self.contexts[context_id].source.document_schema


def yuque_doc(context):
    meta = context.source.metadata.get("yuque")
    return f"{meta['book']}/{meta['slug']}" if meta else None


def resolve_alias(target, reviews, tutorials):
    if isinstance(target, str):
        ids = [c.id for c in reviews if c.title == target]
        assert len(ids) == 1, (target, len(ids))
        return tuple(ids)
    doc = [c for c in tutorials if yuque_doc(c) == target["doc"]]
    assert doc, target
    if "titles" not in target:
        return tuple(c.id for c in doc)
    ids = []
    for title in target["titles"]:
        matched = [c.id for c in doc if c.title == title]
        assert len(matched) == 1, (target["doc"], title, len(matched))
        ids += matched
    return tuple(ids)


def load_corpus(spec, spec_dir):
    contexts = {c.id: c for c in ContextUnit.objects.select_related("source")}
    reviews = [c for c in contexts.values() if c.source.document_schema == "product_review"]
    tutorials = [c for c in contexts.values() if c.source.document_schema == "tutorial"]
    alias_ctx = {alias: resolve_alias(target, reviews, tutorials) for alias, target in spec["aliases"].items()}
    title_ctx = {c.title: c.id for c in reviews}
    attributes = json.loads((spec_dir / spec["attributes"]).read_text(encoding="utf-8")) if "attributes" in spec else {}
    assert set(attributes) <= set(title_ctx), set(attributes) - set(title_ctx)
    return Corpus(
        contexts=contexts,
        evidence={eid: (cid, body) for eid, cid, body in EvidenceUnit.objects.values_list("id", "context_id", "body")},
        alias_ctx=alias_ctx,
        title_ctx=title_ctx,
        attributes=attributes,
    )


def build_scope(schemas, space_id):
    source_ids = tuple(KnowledgeSource.objects.filter(document_schema__in=schemas).values_list("id", flat=True))
    return SearchScope(("public", "internal"), space_id, source_ids)


# ---- D 类条件标注：缺失的售价、重量等数值一律视为不满足 ----

def at_least(value, low):
    return value is not None and (low is None or value >= low)


def at_most(value, high):
    return value is not None and (high is None or value <= high)


CONSTRAINTS = {
    "price": lambda a, v: at_least(a["price"], v[0]) and at_most(a["price"], v[1]),
    "weight_max": lambda a, v: at_most(a["weight"], v),
    "screen_min": lambda a, v: at_least(a["screen"], v),
    "battery_min": lambda a, v: at_least(a["battery_hours"], v),
    "gpu": lambda a, v: a["gpu"] in v,
    "ports": lambda a, v: all(a["ports"][p] for p in v),
    "ports_rich": lambda a, _: all(a["ports"][p] for p in RICH_PORTS),
    "thin_light": lambda a, _: at_most(a["weight"], THIN_LIGHT_MAX_KG),
    "oled": lambda a, v: a["oled"] is v,
    "gaming": lambda a, v: a["gaming"] is v,
}


def grades_of(item, corpus):
    """返回 {父段 id: 等级}：满足全部条件为 2，多条件时只差一条为 1；手工标注一律为 2。"""
    if "constraints" not in item:
        return {cid: 2 for a in item["rel"] for cid in corpus.alias_ctx[a]}
    grades = {}
    for title, attr in corpus.attributes.items():
        passed = [CONSTRAINTS[key](attr, value) for key, value in item["constraints"].items()]
        if all(passed):
            grades[corpus.title_ctx[title]] = 2
        elif len(passed) > 1 and sum(passed) == len(passed) - 1:
            grades[corpus.title_ctx[title]] = 1
    return grades


# ---- 指标 ----

def set_metrics(order, grades):
    relevant = {cid for cid, g in grades.items() if g == 2}
    top5, top10 = order[:5], order[:10]
    dcg = sum((2 ** grades.get(cid, 0) - 1) / math.log2(i + 2) for i, cid in enumerate(top5))
    ideal = sorted(grades.values(), reverse=True)[:5]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return {"p@5": sum(cid in relevant for cid in top5) / min(len(relevant), 5),  # 按 min(5, 答案数) 归一，满分为 1
            "ndcg@5": dcg / idcg if idcg else 0.0,
            "r@10": sum(cid in relevant for cid in top10) / min(len(relevant), 10)}


def hit_metrics(ranks):
    return {"H@1": mean(r == 1 for r in ranks),
            "H@5": mean(r is not None and r <= 5 for r in ranks),
            "MRR@10": mean(1 / r if r is not None and r <= 10 else 0 for r in ranks)}


def parent_order(candidates):
    return list(dict.fromkeys(c.context_id for c in candidates))


def first_rank(order, rel_ids):
    return next((i for i, cid in enumerate(order, 1) if cid in rel_ids), None)


def has_facts(body, facts):
    return all(f in body for f in facts)


# ---- 评测与报告 ----

def evaluate_query(item, scope, schemas, corpus, collector, pipeline):
    """跑一条查询，返回一行结果；答案只保留 schemas 范围内的父段。"""
    routes = collector.collect(item["q"], scope, CANDIDATES_PER_ROUTE)
    fused = pipeline.run(SearchRequest(item["q"], scope, TOP_PARENTS), routes)
    keyword, vector = routes.routes.get("keyword", []), routes.routes.get("vector", [])
    orders = {"hybrid": [c.context_id for c in fused.contexts],
              "keyword": parent_order(keyword),
              "vector": parent_order(vector)}
    grades = {cid: g for cid, g in grades_of(item, corpus).items() if corpus.schema_of(cid) in schemas}
    rel_ids = {cid for cid, g in grades.items() if g == 2}
    if "constraints" in item:
        item = {**item, "rel": sorted(corpus.label(cid) for cid in rel_ids)}
        assert item["rel"], f"{item['id']} 条件下没有答案"
    else:
        item = {**item, "rel": [a for a in item["rel"] if set(corpus.alias_ctx[a]) & rel_ids]}

    row = {**item,
           "top5": [corpus.label(cid) for cid in orders["hybrid"][:5]],
           "ranks": {m: first_rank(o, rel_ids) for m, o in orders.items()},
           "top1_cos": vector[0].score if vector else None,
           "top1_bm25": keyword[0].score if keyword else None}
    by_schema = {}
    for cid in rel_ids:
        by_schema.setdefault(corpus.schema_of(cid), set()).add(cid)
    row["source_ranks"] = {schema: {m: first_rank(o, ids) for m, o in orders.items()}
                           for schema, ids in sorted(by_schema.items())}
    if item["cat"] == "D":
        row["set"] = {m: set_metrics(o, grades) for m, o in orders.items()}
        row["n_rel"] = len(rel_ids)
    if item.get("pair") and len(item["rel"]) > 1:
        top5 = set(orders["hybrid"][:5])
        row["pair_both_top5"] = all(set(corpus.alias_ctx[a]) & top5 for a in item["rel"])
    if item["facts"] and rel_ids:
        # 融合后的子块序列：按父段名次展开其命中子块（与 API 返回证据顺序一致）
        children = [m for ctx in fused.contexts for m in ctx.matches]
        row["fact_child_rank"] = next(
            (i for i, m in enumerate(children, 1)
             if m.context_id in rel_ids and has_facts(corpus.evidence[m.evidence_id][1], item["facts"])), None)
        row["fact_in_any_child"] = any(
            cid in rel_ids and has_facts(body, item["facts"]) for cid, body in corpus.evidence.values())
    return row


def score_stats(rows, key):
    values = [r[key] or 0 for r in rows]
    return {"min": min(values), "max": max(values), "mean": mean(values)}


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


def summarize(rows):
    pos = [r for r in rows if r["rel"]]
    neg = [r for r in rows if not r["rel"]]
    by_cat = {}
    for cat in sorted({r["cat"] for r in pos}) + ["ALL"]:
        sub = [r for r in pos if cat in ("ALL", r["cat"])]
        by_cat[cat] = {"n": len(sub), **{m: hit_metrics([r["ranks"][m] for r in sub]) for m in METHODS}}
    d_rows = [r for r in rows if "set" in r]
    d_set = {m: {k: mean(r["set"][m][k] for r in d_rows) for k in SET_METRICS} for m in METHODS} if d_rows else None
    return {"by_cat": by_cat, "d_n": len(d_rows), "d_set": d_set, "failures": failures(pos),
            "cos": {"pos": score_stats(pos, "top1_cos"), "neg": score_stats(neg, "top1_cos")},
            "bm25": {"pos": score_stats(pos, "top1_bm25"), "neg": score_stats(neg, "top1_bm25")}}


def detail_line(r):
    extra = ""
    if "fact_child_rank" in r:
        extra = f" fact子块#{r['fact_child_rank']}{'' if r['fact_in_any_child'] else '(范围内无)'}"
    if "pair_both_top5" in r:
        extra += f" 双命中@5={r['pair_both_top5']}"
    if "set" in r:
        h = r["set"]["hybrid"]
        extra += f" 答案{r['n_rel']}台 P@5={h['p@5']:.2f} nDCG@5={h['ndcg@5']:.2f} R@10={h['r@10']:.2f}"
    ranks = "/".join(str(r["ranks"][m]) for m in METHODS)
    if len(r.get("source_ranks", {})) > 1:
        extra += " 分来源 " + " ".join(
            f"{SCHEMA_NAMES.get(schema, schema)}={'/'.join(str(v[m]) for m in METHODS)}"
            for schema, v in r["source_ranks"].items())
    return (f"{r['id']} H/K/V={ranks} cos={(r['top1_cos'] or 0):.3f} bm25={(r['top1_bm25'] or 0):.1f}{extra}"
            f" | {r['q']} -> {r['top5']}")


def print_report(scope_name, rows, summary):
    print(f"\n===== scope={scope_name} =====")
    for r in rows:
        print(detail_line(r))
    print("-- 汇总（正例）")
    for cat, s in summary["by_cat"].items():
        print("  ".join([f"{cat}(n={s['n']})"] + [
            f"{m}: H@1={s[m]['H@1']:.2f} H@5={s[m]['H@5']:.2f} MRR@10={s[m]['MRR@10']:.3f}" for m in METHODS]))
    if summary["d_set"]:
        print("  ".join([f"D 集合指标(n={summary['d_n']})"] + [
            f"{m}: " + " ".join(f"{k}={v:.3f}" for k, v in summary["d_set"][m].items()) for m in METHODS]))
    fails = summary["failures"]
    print(f"-- 召回失败（两路前 {CANDIDATES_PER_ROUTE} 个子块均无答案）{len(fails['recall'])} 项：{' '.join(fails['recall'])}")
    print(f"-- 排序失败（已召回，未进入混合前 5）{len(fails['ranking'])} 项：{' '.join(fails['ranking'])}")
    cos, bm25 = summary["cos"], summary["bm25"]
    print(f"-- top1 余弦：正例 min={cos['pos']['min']:.3f} mean={cos['pos']['mean']:.3f}"
          f"；负例 max={cos['neg']['max']:.3f} mean={cos['neg']['mean']:.3f}")
    print(f"-- top1 BM25：正例 min={bm25['pos']['min']:.2f}；负例 max={bm25['neg']['max']:.2f}")


def main(spec_path, out_path):
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    corpus = load_corpus(spec, spec_path.parent)
    embedder = components.embedding_provider()
    collector = components.recall_collector(embedder)
    pipeline = components.post_recall_pipeline()
    scope_schemas = spec.get("scopes", DEFAULT_SCOPES)

    rows = []
    for name, schemas in scope_schemas.items():
        scope = build_scope(schemas, embedder.space_id)
        rows += [{"scope": name, **evaluate_query(item, scope, schemas, corpus, collector, pipeline)}
                 for item in spec["queries"]]
    Path(out_path).write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for name in scope_schemas:
        scope_rows = [r for r in rows if r["scope"] == name]
        print_report(name, scope_rows, summarize(scope_rows))
    print_scope_changes(rows, list(scope_schemas))


def print_scope_changes(rows, scope_names):
    """列出相邻两个范围里答案相同、混合排名却不同的查询，观察扩充语料对原有问题的干扰。"""
    by_key = {(r["scope"], r["id"]): r for r in rows}
    for before, after in zip(scope_names, scope_names[1:]):
        print(f"\n-- 排名变化 {before} -> {after}（答案相同的查询）")
        for r in rows:
            if r["scope"] != before or not r["rel"]:
                continue
            other = by_key[(after, r["id"])]
            if other["rel"] == r["rel"] and other["ranks"]["hybrid"] != r["ranks"]["hybrid"]:
                print(f"  {r['id']} {r['ranks']['hybrid']} -> {other['ranks']['hybrid']} | {r['q']} -> {other['top5']}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
