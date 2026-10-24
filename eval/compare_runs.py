"""对比多次召回评测结果：第一个文件为基线，其余为实验组。只读结果 JSON，不需要数据库或 Django。

    .venv/bin/python eval/compare_runs.py .runtime/eval/corpus-v3/results-v8.json \
      .runtime/eval/corpus-v3/rrf/results-k*.json --scope all

输出两部分：
1. 汇总表：全部（不含 D）、A～F（不含 D）、D（含集合指标）及 T／X／K／U／R 类的混合指标，召回失败与排序失败条数，
   以及按固定 dev/test 分层的 MRR@10 相对基线变化；
2. 逐条变化：每个实验组相对基线混合名次变化的查询，标出进入／跌出前 5，
   并列出新进入前 5、但不在本条答案中的父段，供增量补标核对。
"""
import argparse
import json
from pathlib import Path
from statistics import mean

from metrics import failures, hit_metrics, METRIC_VERSION

# D 类只经推荐接口按集合指标评测，不计入全部、A～F、分层和失败清单
ORIGINAL_CATS = set("ABCEF")
CAT_COLUMNS = ("T", "X", "K", "U", "R")


def load(path, scope):
    rows = [r for r in json.loads(Path(path).read_text(encoding="utf-8")) if r["scope"] == scope]
    assert rows, f"{path} 中没有范围 {scope}"
    assert all(r.get("metric_version") == METRIC_VERSION for r in rows), "指标口径不是 strict-v2，需重跑"
    assert len({r["id"] for r in rows}) == len(rows), f"{path} 中存在重复查询编号"
    return {r["id"]: r for r in rows}


def run_name(path):
    return Path(path).stem.removeprefix("results-")


def hybrid(rows):
    return hit_metrics([r["ranks"]["hybrid"] for r in rows]) if rows else None


def summarize(rows):
    positives = [r for r in rows.values() if r["rel"]]
    recall = [r for r in positives if r["cat"] != "D"]
    d_rows = [r for r in positives if r["cat"] == "D" and "set" in r]
    halves = [[r for r in recall if r.get("split") == split] for split in ("dev", "test")]
    fails = failures([r for r in recall if not r.get("source_gap")])
    return {
        "ALL": hybrid(recall),
        "A~F": hybrid([r for r in positives if r["cat"] in ORIGINAL_CATS]),
        "D": hybrid([r for r in positives if r["cat"] == "D"]),
        "D_set": {k: mean(r["set"]["hybrid"][k] for r in d_rows) for k in ("precision", "ndcg@5")} if d_rows else None,
        **{cat: hybrid([r for r in positives if r["cat"] == cat]) for cat in CAT_COLUMNS},
        "halves": [hybrid(half)["MRR@10"] if half else None for half in halves],
        "recall_fail": fails["recall"],
        "ranking_fail": fails["ranking"],
    }


COLUMNS = [("全部 H@1", "ALL", "H@1"), ("全部 H@5", "ALL", "H@5"), ("全部 MRR", "ALL", "MRR@10"),
           ("A~F H@5", "A~F", "H@5"), ("A~F MRR", "A~F", "MRR@10"),
           ("D H@5", "D", "H@5"), ("D MRR", "D", "MRR@10"), ("D Precision", "D_set", "precision"), ("D nDCG@5", "D_set", "ndcg@5"),
           *((f"{cat} MRR", cat, "MRR@10") for cat in CAT_COLUMNS)]


def cell(summary, group, key):
    value = summary[group][key] if summary[group] else None
    return "-" if value is None else f"{value:.3f}"


def summary_table(names, summaries):
    header = ["运行", *(title for title, _, _ in COLUMNS), "召回失败", "排序失败", "dev ΔMRR", "test ΔMRR"]
    base = summaries[0]
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    for name, s in zip(names, summaries):
        cells = [name, *(cell(s, group, key) for _, group, key in COLUMNS),
                 str(len(s["recall_fail"])), str(len(s["ranking_fail"])),
                 *(f"{now - before:+.3f}" if now is not None and before is not None else "-" for now, before in zip(s["halves"], base["halves"]))]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def rank_key(rank):
    return rank if rank is not None else float("inf")


def changes(base, run):
    """逐条列出混合名次变化（只看有答案的查询），先列变差的。"""
    lines = []
    for qid, before in base.items():
        after = run[qid]
        old, new = before["ranks"]["hybrid"], after["ranks"]["hybrid"]
        if not after["rel"] or old == new:
            continue
        flag = ""
        if rank_key(old) <= 5 < rank_key(new):
            flag = " 跌出前5"
        elif rank_key(new) <= 5 < rank_key(old):
            flag = " 进入前5"
        if old == 1 and new != 1:
            flag += " 丢失第1名"
        lines.append((rank_key(new) > rank_key(old), f"  {qid} {old} -> {new}{flag} | {after['q']}"))
    worse = sum(is_worse for is_worse, _ in lines)
    body = [text for _, text in sorted(lines, key=lambda item: not item[0])]
    return f"变差 {worse} 条，变好 {len(lines) - worse} 条", body


def new_unlabeled(base, run):
    """答案名次不变也可能出现新父段，不能只从名次变化的查询中补标。"""
    lines = []
    for qid, after in run.items():
        if not after["rel"]:
            continue
        labels = [label for label in after["top5"]
                  if label not in base[qid]["top5"] and label not in after["rel"]]
        if labels:
            lines.append(f"  {qid} | {after['q']} | 新进前5未标注：{labels}")
    return lines


def validate_queries(base, run):
    assert run.keys() == base.keys(), "各结果的查询集不一致"
    for qid, before in base.items():
        assert before.get("metric_version") == run[qid].get("metric_version"), "指标口径不同，需重跑"
        for key in ("q", "cat", "rel", "facts", "constraints", "pair", "needs", "split", "group", "qrels_complete", "source_gap", "metric_version"):
            assert before.get(key) == run[qid].get(key), f"{qid} 的 {key} 不一致，需按同一标注重跑"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baseline", help="基线结果 JSON")
    parser.add_argument("runs", nargs="+", help="实验组结果 JSON")
    parser.add_argument("--scope", default="all", help="对比的检索范围，默认 all")
    args = parser.parse_args()

    paths = [args.baseline, *args.runs]
    runs = [load(path, args.scope) for path in paths]
    for run in runs[1:]:
        validate_queries(runs[0], run)
    names = [run_name(path) for path in paths]
    summaries = [summarize(run) for run in runs]

    print(f"范围 {args.scope}，基线 {names[0]}\n")
    print(summary_table(names, summaries))
    for name, run, summary in zip(names[1:], runs[1:], summaries[1:]):
        title, body = changes(runs[0], run)
        print(f"\n== {name} 相对基线：{title}")
        if summary["recall_fail"] != summaries[0]["recall_fail"]:
            print(f"  召回失败与基线不同：{summary['recall_fail']}")
        print("\n".join(body))
        unlabeled = new_unlabeled(runs[0], run)
        print(f"-- 新进前5未标注（含答案名次未变化的查询）：{len(unlabeled)} 条")
        print("\n".join(unlabeled))


if __name__ == "__main__":
    main()
