"""初步召回评测：父段级 Hit/MRR、分路排名、事实子块排名、负例分数；
D 类严格满足全部条件才相关，只报集合指标，不计入 ALL、宏平均、闭集和失败清单；
另报实际返回精确率、完整 Recall@10、必要需求覆盖（分单需求与复合需求）和按问法风格的分组指标。

答案按来源类别分别报三路名次，区分召回失败（两路候选中都没有）与排序失败（已召回但未进入混合前 5）。
查询集的 scopes 定义若干检索范围（范围名 -> document_schema 列表），每个范围各跑一遍；
答案按范围过滤，范围内没有答案的查询在该范围按负例统计。
别名可指向评测标题（字符串），或指向语雀文档（教程、知识、工具条目、排障指南、案例）的父段
{"doc": "book/slug", "titles": [...]}，省略 titles 表示整篇。

查询集 queries.json 在本目录，规格文件由查询集的 specs 指定（products/specs/）；语料原文与评测结果放在被忽略的 .runtime/eval/。
评测只读正式库，镜像不含本目录，运行时挂载：

    docker compose --env-file .env.docker -p itxia run --rm --no-deps \
      -v "$PWD/eval:/app/eval:ro" -v "$PWD/.runtime/eval:/data" -e PYTHONPATH=/app \
      app python eval/recall_eval.py eval/queries.json /data/corpus-v3/results-v7.json

可选参数临时覆盖检索配置（不改 settings），用于参数实验：--scope 只跑指定范围（可重复），
--rrf-k、--vector-weight 调整 RRF，--search-mode {off,document,both} 选择关键词路搜索模式的使用范围，
--synonyms／--no-synonyms 切换查询端同义扩展。镜像中的代码未重新构建时，可另挂载 retrieval、config 目录。
多次运行的结果用 compare_runs.py 对比。
"""
import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings  # noqa: E402

from catalog.models import ContextUnit, EvidenceUnit, KnowledgeSource  # noqa: E402
from config import components  # noqa: E402
from contracts.types import SearchRequest, SearchScope  # noqa: E402
from cases import digest, style_of
from metrics import (METHODS, SCHEMA_NAMES, METRIC_VERSION, average_sets, failures, hit_metrics,
                     need_coverage, set_metrics)  # noqa: E402

CANDIDATES_PER_ROUTE = 100
TOP_PARENTS = 20
RICH_PORTS = ("usb_a", "usb_c", "video_out")  # 视频输出含 HDMI、DP 与支持 DP 的 USB-C；网口不作要求
THIN_LIGHT_MAX_KG = 1.5
DEFAULT_SCOPES = {"reviews": ["product_review"]}
LABEL_PREFIXES = {"purchase_guide": "指南:", "tutorial": "教程:", "knowledge": "知识:", "tool_card": "工具:",
                  "troubleshooting": "排障:", "experience_case": "案例:"}


@dataclass
class Corpus:
    contexts: dict    # 父段 id -> ContextUnit
    evidence: dict    # 子块 id -> (父段 id, 正文)
    alias_ctx: dict   # 查询集别名 -> 父段 id 元组
    title_ctx: dict   # 评测标题 -> 父段 id
    specs: dict       # 评测标题（规格 key）-> 规格记录

    def label(self, context_id):
        for alias, ids in self.alias_ctx.items():
            if context_id in ids:
                return alias
        c = self.contexts[context_id]
        return LABEL_PREFIXES.get(c.source.document_schema, "") + c.title.split(" > ")[-1][:16]

    def schema_of(self, context_id):
        return self.contexts[context_id].source.document_schema


def yuque_doc(context):
    meta = context.source.metadata.get("yuque")
    return f"{meta['book']}/{meta['slug']}" if meta else None


def resolve_alias(target, reviews, yuque):
    if isinstance(target, str):
        ids = [c.id for c in reviews if c.title == target]
        assert len(ids) == 1, (target, len(ids))
        return tuple(ids)
    doc = [c for c in yuque if yuque_doc(c) == target["doc"]]
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
    yuque = [c for c in contexts.values() if c.source.source_type == "yuque"]
    alias_ctx = {alias: resolve_alias(target, reviews, yuque) for alias, target in spec["aliases"].items()}
    title_ctx = {c.title: c.id for c in reviews}
    records = json.loads((spec_dir / spec["specs"]).read_text(encoding="utf-8")) if "specs" in spec else []
    specs = {record["key"]: record for record in records}
    assert set(specs) <= set(title_ctx), set(specs) - set(title_ctx)
    return Corpus(
        contexts=contexts,
        evidence={eid: (cid, body) for eid, cid, body in EvidenceUnit.objects.values_list("id", "context_id", "body")},
        alias_ctx=alias_ctx,
        title_ctx=title_ctx,
        specs=specs,
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
    "price": lambda s, v: at_least(s["price_cny"], v[0]) and at_most(s["price_cny"], v[1]),
    "weight_max": lambda s, v: at_most(s["weight_kg"], v),
    "screen_min": lambda s, v: at_least(s["screen_inch"], v),
    "battery_min": lambda s, v: at_least(s["battery_hours"], v),
    "gpu": lambda s, v: s["gpu"] in v,
    "ports": lambda s, v: all(s["ports"][p] for p in v),
    "ports_rich": lambda s, _: all(s["ports"][p] for p in RICH_PORTS),
    "thin_light": lambda s, _: at_most(s["weight_kg"], THIN_LIGHT_MAX_KG),
    "oled": lambda s, v: s["panel"] is not None and (s["panel"] == "oled") is v,
    "gaming": lambda s, v: s["is_gaming"] is v,
}


def grades_of(item, corpus):
    """返回 {父段 id: 等级}：满足全部硬条件为 2，不满足为 0；手工标注为 2。"""
    if "constraints" not in item:
        return {cid: 2 for a in item["rel"] for cid in corpus.alias_ctx[a]}
    grades = {}
    for title, spec in corpus.specs.items():
        passed = [CONSTRAINTS[key](spec, value) for key, value in item["constraints"].items()]
        if all(passed):
            grades[corpus.title_ctx[title]] = 2
    return grades


# ---- 指标 ----

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
    keyword_route = next(r for r in collector.retrievers if r.name == "keyword")
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

    row = {**item, "metric_version": METRIC_VERSION,
           "top5": [corpus.label(cid) for cid in orders["hybrid"][:5]],
           "ranks": {m: first_rank(o, rel_ids) for m, o in orders.items()},
           "top1_cos": vector[0].score if vector else None,
           "top1_bm25": keyword[0].score if keyword else None,
           "keyword_terms": keyword_route.query_terms(item["q"])}
    by_schema = {}
    for cid in rel_ids:
        by_schema.setdefault(corpus.schema_of(cid), set()).add(cid)
    row["source_ranks"] = {schema: {m: first_rank(o, ids) for m, o in orders.items()}
                           for schema, ids in sorted(by_schema.items())}
    row["set"] = {m: set_metrics(o[:TOP_PARENTS], grades) for m, o in orders.items()}
    if not item.get("qrels_complete", item["cat"] == "D"):
        for scores in row["set"].values():
            scores["recall@10"] = None
    row["n_rel"] = len(rel_ids)
    if item.get("needs") and item["cat"] not in ("D", "G") and not item.get("source_gap"):
        bodies = {cid: c.body for cid, c in corpus.contexts.items()}
        row["needs_at5"] = {m: need_coverage(item["needs"], o, bodies, corpus.alias_ctx) for m, o in orders.items()}
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
    return {"min": min(values), "max": max(values), "mean": mean(values)} if values else None


def grouped_hits(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    return {name: {"n": len(sub), **{m: hit_metrics([r["ranks"][m] for r in sub]) for m in METHODS}}
            for name, sub in sorted(groups.items())}


def need_summary(rows):
    return {m: {"n": len(rows), "all": mean(r["needs_at5"][m]["all"] for r in rows) if rows else None} for m in METHODS}


def summarize(rows):
    pos = [r for r in rows if r["rel"]]
    neg = [r for r in rows if not r["rel"]]
    # D 类由推荐接口按集合指标评测，不进入召回主指标（ALL、宏平均、闭集、失败清单）
    recall = [r for r in pos if r["cat"] != "D"]
    by_cat = grouped_hits(pos, lambda r: r["cat"])
    by_cat["ALL"] = grouped_hits(recall, lambda r: "ALL").get("ALL")
    cats = [c for c in by_cat if c not in ("D", "ALL")]
    by_cat["MACRO"] = {"n": len(cats), **{m: {k: mean(by_cat[c][m][k] for c in cats) for k in ("H@1", "H@5", "MRR@10")}
                                          for m in METHODS}} if cats else None
    d_rows = [r for r in rows if r["cat"] == "D"]
    d_set = {m: average_sets(d_rows, m) for m in METHODS} if d_rows else None
    closed = [r for r in recall if r.get("qrels_complete") and not r.get("source_gap")]
    partial = [r for r in recall if not r.get("qrels_complete") and not r.get("source_gap")]
    need_rows = [r for r in rows if "needs_at5" in r]
    pairs = [r for r in rows if "pair_both_top5" in r]
    return {"metric_version": METRIC_VERSION, "closed_set": {m: average_sets(closed, m) for m in METHODS},
            "known_label_precision_lower_bound": {m: {"n": len(partial), "precision": mean(r["set"][m]["precision"] for r in partial) if partial else None} for m in METHODS},
            "needs_at5": need_summary(need_rows),
            "needs_at5_single": need_summary([r for r in need_rows if len(r["needs"]) == 1]),
            "needs_at5_multi": need_summary([r for r in need_rows if len(r["needs"]) > 1]),
            "pair_both_top5": {"n": len(pairs), "passed": sum(r["pair_both_top5"] for r in pairs)},
            "source_gaps": [r["id"] for r in rows if r.get("source_gap")],
            "by_cat": by_cat, "by_style": grouped_hits(recall, style_of),
            "d_n": len(d_rows), "d_set": d_set, "failures": failures([r for r in recall if not r.get("source_gap")]),
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
        extra += f" 相关{r['n_rel']}项 precision={h['precision']:.2f} Recall@10={h['recall@10']}"
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
    print("-- 汇总（正例；ALL 与 MACRO 不含 D，MACRO 为各类等权平均）")
    for title, groups in (("类别", summary["by_cat"]), ("问法风格", summary["by_style"])):
        for name, s in groups.items():
            if s:
                print("  ".join([f"{title} {name}(n={s['n']})"] + [
                    f"{m}: H@1={s[m]['H@1']:.2f} H@5={s[m]['H@5']:.2f} MRR@10={s[m]['MRR@10']:.3f}" for m in METHODS]))
    if summary["d_set"]:
        print("  ".join([f"D 集合指标(n={summary['d_n']})"] + [
            f"{m}: " + str(summary["d_set"][m]) for m in METHODS]))
    fails = summary["failures"]
    print(f"-- 召回失败（两路前 {CANDIDATES_PER_ROUTE} 个子块均无答案）{len(fails['recall'])} 项：{' '.join(fails['recall'])}")
    print(f"-- 排序失败（已召回，未进入混合前 5）{len(fails['ranking'])} 项：{' '.join(fails['ranking'])}")
    for key in ("closed_set", "known_label_precision_lower_bound", "needs_at5", "needs_at5_single", "needs_at5_multi",
                "pair_both_top5", "source_gaps"):
        print(f"-- {key}: {summary[key]}")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path, help="查询集 JSON")
    parser.add_argument("out", type=Path, help="结果 JSON 输出路径")
    parser.add_argument("--scope", action="append", help="只跑指定范围，可重复；默认跑查询集中的全部范围")
    parser.add_argument("--ids", nargs="+", help="只跑指定题号，用于复现和互不重叠的分批评测")
    parser.add_argument("--rrf-k", type=int)
    parser.add_argument("--vector-weight", type=float, help="向量路 RRF 权重，关键词路保持 settings 中的值")
    parser.add_argument("--search-mode", choices=("off", "document", "both"), help="关键词路 jieba 搜索模式的使用范围")
    parser.add_argument("--synonyms", action=argparse.BooleanOptionalAction, help="关键词路查询端同义扩展")
    return parser.parse_args()


def retrieval_config(args):
    """参数与 settings 合并后的实际检索配置，写入报告开头。"""
    weights = dict(settings.RETRIEVAL_RRF_WEIGHTS)
    if args.vector_weight is not None:
        weights["vector"] = args.vector_weight
    return {
        "rrf_k": settings.RETRIEVAL_RRF_K if args.rrf_k is None else args.rrf_k,
        "rrf_weights": weights,
        "search_mode": settings.RETRIEVAL_KEYWORD_SEARCH_MODE if args.search_mode is None else args.search_mode,
        "synonyms": settings.RETRIEVAL_KEYWORD_SYNONYMS if args.synonyms is None else args.synonyms,
    }


def main(args):
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    corpus = load_corpus(spec, args.spec.parent)
    config = retrieval_config(args)
    embedder = components.embedding_provider()
    collector = components.recall_collector(embedder, search_mode=config["search_mode"], synonyms=config["synonyms"])
    pipeline = components.post_recall_pipeline(rrf_k=config["rrf_k"], rrf_weights=config["rrf_weights"])
    scope_schemas = spec.get("scopes", DEFAULT_SCOPES)
    if args.scope:
        unknown = set(args.scope) - set(scope_schemas)
        assert not unknown, f"查询集未定义范围：{unknown}"
        scope_schemas = {name: scope_schemas[name] for name in args.scope}
    print(f"检索配置 {json.dumps(config, ensure_ascii=False)}；查询集 {spec.get('version', args.spec.name)}，"
          f"{len(spec['queries'])} 条；语料 {KnowledgeSource.objects.count()} 个来源、"
          f"{len(corpus.contexts)} 个父段、{len(corpus.evidence)} 个子块")

    manifest = {"cases_sha256": digest(spec), "specs_sha256": digest(corpus.specs), "config": config,
                "corpus_sha256": digest(sorted((str(c.id), c.body, c.source.document_schema) for c in corpus.contexts.values()))}
    queries = spec["queries"]
    if args.ids:
        assert set(args.ids) <= {q["id"] for q in queries}, "存在未知题号"
        queries = [q for q in queries if q["id"] in args.ids]
    rows = []
    for name, schemas in scope_schemas.items():
        scope = build_scope(schemas, embedder.space_id)
        for i, item in enumerate(queries, 1):
            rows.append({"scope": name, "run_meta": manifest,
                         **evaluate_query(item, scope, schemas, corpus, collector, pipeline)})
            if i % 20 == 0:
                print(f"{name}: 已评测 {i}/{len(queries)}", flush=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for name in scope_schemas:
        scope_rows = [r for r in rows if r["scope"] == name]
        print_report(name, scope_rows, summarize(scope_rows))
    args.out.with_suffix(".summary.json").write_text(json.dumps(
        {name: summarize([r for r in rows if r["scope"] == name]) for name in scope_schemas},
        ensure_ascii=False, indent=2), encoding="utf-8")
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
    main(parse_args())
