"""评测用例与证据核验；离线使用，不导入 Django、不调用模型。"""
import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

TARGETS = dict(A=30, B=25, C=25, D=30, E=20, F=25, T=35, X=20, K=40, U=40, R=45, G=25)
AGENT_TARGETS = dict(A=3, B=3, C=3, D=10, E=6, F=4, T=5, X=8, K=4, U=4, R=4, G=6)
# D 只经推荐接口评测，不计入召回主指标
RECALL_CATS = [c for c in TARGETS if c != "D"]
STYLES = ("standard", "abbrev", "colloquial")
G_TYPES = ("near_model", "missing_model", "missing_attr", "missing_topic", "out_of_scope")
# 资料原文术语和模板套话，不应出现在新增题面中
JARGON = ("日常应用仿真", "人位", "实测", "资料", "想确认一下", "能帮我看看不", "请说明测试环境")
X_ALIAS_LIMIT = 4


def style_of(item):
    return item.get("style") or {"B": "abbrev", "C": "colloquial"}.get(item["cat"], "standard")


def normalized(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def contains(body, quote):
    return bool(quote) and normalized(quote) in normalized(body)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def resolve(target, contexts):
    if isinstance(target, str):
        return [c for c in contexts if c["title"] == target and c["source"]["schema"] == "product_review"]
    rows = []
    for c in contexts:
        meta = c["source"]["metadata"].get("yuque", {})
        if f"{meta.get('book', '')}/{meta.get('slug', '')}" == target["doc"]:
            if "titles" not in target or c["title"] in target["titles"]:
                rows.append(c)
    return rows


def validate(spec, contexts=None, full=False, recall_full=False):
    queries, aliases = spec["queries"], spec["aliases"]
    ids, questions, groups = set(), set(), {}
    resolved = {a: resolve(t, contexts) for a, t in aliases.items()} if contexts is not None else None
    for item in queries:
        tag = item["id"]
        assert tag not in ids, f"重复 id: {tag}"
        ids.add(tag)
        assert item["q"] not in questions, f"重复问题: {tag}"
        questions.add(item["q"])
        assert item["cat"] in TARGETS and tag.startswith(item["cat"]), tag
        assert item.get("split", "dev") in ("dev", "test"), tag
        group = item.get("group", tag)
        split = item.get("split", "dev")
        assert groups.setdefault(group, split) == split, f"分组跨集合: {group}"
        for ref in item.get("rel", []):
            assert ref in aliases, (tag, ref)
        needs = item.get("needs", [])
        checks = item.get("agent", {}).get("turn_checks", [])
        for needs in [needs, *(c["needs"] for c in checks)]:
            assert len({n["id"] for n in needs}) == len(needs), f"重复需求: {tag}"
            for need in needs:
                assert need["answer"].strip(), tag
                evidence = need.get("evidence", [])
                assert evidence or item["cat"] in ("D", "G"), f"缺证据: {tag}/{need['id']}"
                for e in evidence:
                    assert e["ref"] in aliases and e["quote"].strip(), (tag, e)
                    if resolved is not None:
                        assert any(contains(c["body"], e["quote"]) for c in resolved[e["ref"]]), \
                            f"原文不存在: {tag}/{need['id']}/{e['ref']}: {e['quote']}"
        needs = item.get("needs", [])
        assert style_of(item) in STYLES, f"未知问法风格: {tag}"
        assert (item["cat"] == "G") == ("g_type" in item), f"g_type 只用于且必须用于 G 类: {tag}"
        assert item.get("g_type", G_TYPES[0]) in G_TYPES, f"未知无答案类型: {tag}"
        if item.get("agent"):
            assert needs, f"Agent 缺要点: {tag}"
            assert item["agent"].get("mode", "answer") in ("answer", "no_answer", "recommend", "clarify"), tag
            turns = item["agent"].get("turns", [])
            assert all(isinstance(t, str) and t.strip() for t in turns), tag
            assert len(checks) == len(turns), f"缺少逐轮验收: {tag}"
            assert all(c.get("needs") for c in checks), f"追问缺必要需求: {tag}"
        if full or recall_full:
            assert "group" in item and "split" in item, tag
            assert needs, f"缺少必要需求: {tag}"
            if item.get("origin") == "expanded":
                assert not [w for w in JARGON if w in item["q"]], f"题面含原文术语或套话: {tag}"
                if item["cat"] == "X":
                    assert len({n["evidence"][0]["ref"] for n in needs}) >= 2, f"X 类需跨文档复合: {tag}"
    if full or recall_full:
        usage = Counter(ref for q in queries if q["cat"] == "X" for ref in q.get("rel", [])
                        if isinstance(aliases[ref], dict))
        overused = {ref: n for ref, n in usage.items() if n > X_ALIAS_LIMIT}
        assert not overused, f"X 类教程复用过多: {overused}"
    by_id = {q["id"]: q for q in queries}
    for item in queries:
        if item.get("variant_of"):
            parent = by_id[item["variant_of"]]
            assert item.get("group") == parent.get("group"), f"变体未同组: {item['id']}"
    counts = Counter(q["cat"] for q in queries)
    agents = [q for q in queries if q.get("agent")]
    if full or recall_full:
        assert counts == TARGETS
        assert Counter(q["split"] for q in queries) == dict(dev=300, test=60)
        added = [q for q in queries if q.get("origin") == "expanded"]
        assert len(added) == 190
        assert sum(q.get("construction") == "new_fact" for q in added) >= 140
        assert sum(q.get("construction") == "paraphrase" for q in added) <= 50
    if full:
        assert Counter(q["cat"] for q in agents) == AGENT_TARGETS
        assert Counter(q["split"] for q in queries) == dict(dev=300, test=60)
        assert Counter(q["split"] for q in agents) == dict(dev=40, test=20)
        assert sum(bool(q["agent"].get("turns")) for q in agents) == 10
    return {"queries": len(queries), "by_category": dict(counts), "agent": len(agents),
            "splits": dict(Counter(q.get("split", "dev") for q in queries)), "sha256": digest(spec)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--corpus", type=Path, help="只读导出的父段 JSON（包含 title/body/source）")
    parser.add_argument("--recall-full", action="store_true", help="核验 360 题主集配额和数据划分")
    parser.add_argument("--full", action="store_true", help="核验 360/60 配额与数据划分")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    contexts = json.loads(args.corpus.read_text()) if args.corpus else None
    print(json.dumps(validate(spec, contexts, args.full, args.recall_full), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
