"""上层 LLM 模拟评测（机型规格库方案 8.2 节 P3）：用一个 LLM 加工具定义模拟上层系统，衡量工具定义是否清楚。

1. 工具选择：全部查询中选对工具的比例；D 类应选机型推荐，其余应选知识检索。
2. 条件换算：D 类有标准条件的查询，逐条列出 LLM 给出的原子条件与标准条件的差异。
3. 端到端：按 LLM 给出的参数调用推荐服务，D 类 P@5、nDCG@5 与链路结果（标准条件）对比。
4. 补充样例：口语化选购与多轮追问，答案为满足标准条件的全部机型。

只看 LLM 第一轮回复的工具调用，不执行多步对话；参数不合法时记为错误，不重试。
提示词和工具定义取自 products/tool-definitions.md。LLM 通过 OpenAI 兼容的 /chat/completions 调用，
在环境变量 EVAL_LLM_BASE_URL、EVAL_LLM_MODEL、EVAL_LLM_API_KEY（可选）中配置。运行方式同 recommend_eval.py：

    docker compose --env-file .env.docker -p itxia run --rm --no-deps \
      -v "$PWD/eval:/app/eval:ro" -v "$PWD/.runtime/eval:/data" -e PYTHONPATH=/app \
      -e EVAL_LLM_BASE_URL -e EVAL_LLM_MODEL -e EVAL_LLM_API_KEY \
      app python eval/llm_eval.py eval/queries.json eval/llm-queries.json /data/corpus-v5/llm-v1.json
"""
import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean
from urllib.request import Request, urlopen

from recommend_eval import VISIBILITIES, Recommender, chain_rows, to_conditions  # 导入时完成 django.setup()
from recall_eval import grades_of, load_corpus, set_metrics

from rest_framework.exceptions import ValidationError  # noqa: E402

from catalog.selectors import scoped_contexts  # noqa: E402
from contracts.types import SearchScope  # noqa: E402
from products.conditions import match  # noqa: E402
from products.models import ProductSpec  # noqa: E402

TOOL_FILE = Path(__file__).resolve().parents[1] / "products/tool-definitions.md"
SEARCH, RECOMMEND = "search_knowledge", "recommend_laptops"


def load_tools(path=TOOL_FILE):
    """工具定义文档中只有提示词使用 text 代码块，只有两个工具定义使用 json 代码块。"""
    text = path.read_text(encoding="utf-8")
    prompt, = re.findall(r"```text\n(.*?)\n```", text, re.S)
    tools = [{"type": "function", "function": json.loads(block)} for block in re.findall(r"```json\n(.*?)\n```", text, re.S)]
    return prompt, tools


class ChatModel:
    def __init__(self, prompt, tools):
        self.url = os.environ["EVAL_LLM_BASE_URL"].rstrip("/") + "/chat/completions"
        self.model, self.api_key = os.environ["EVAL_LLM_MODEL"], os.environ.get("EVAL_LLM_API_KEY", "")
        self.prompt, self.tools = prompt, tools

    def tool_calls(self, messages):
        """返回第一轮回复中的 [(工具名, 参数)]；模型直接回答时为空列表。"""
        body = {"model": self.model, "temperature": 0, "tools": self.tools,
                "messages": [{"role": "system", "content": self.prompt}, *messages]}
        request = Request(self.url, method="POST", data=json.dumps(body).encode("utf-8"),
                          # Cloudflare 会拦截 urllib 默认 UA（error 1010）
                          headers={"Content-Type": "application/json", "User-Agent": "itxia-llm-eval"})
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        with urlopen(request, timeout=120) as response:
            message = json.load(response)["choices"][0]["message"]
        return [(call["function"]["name"], _arguments(call["function"].get("arguments")))
                for call in message.get("tool_calls") or []]


def _arguments(raw):
    """解析工具参数；不是 JSON 对象时原样返回，由 recommend_with 记为参数错误。"""
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return raw
    return value if isinstance(value, dict) else raw


def _normalized(value):
    if isinstance(value, list):
        return sorted(value, key=json.dumps)  # 元素类型可能混杂
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(value, 2)
    return value


def condition_diff(standard, args):
    """{条件名: [标准值, LLM 给出的值]}，数值保留两位小数比较，列表不计顺序。"""
    actual = args.get("conditions") if isinstance(args, dict) else None
    actual = actual if isinstance(actual, dict) else {}
    return {name: [standard.get(name), actual.get(name)] for name in sorted(set(standard) | set(actual))
            if _normalized(standard.get(name)) != _normalized(actual.get(name))}


def recommend_with(recommender, calls):
    """按第一个推荐调用的参数推荐，返回 (参数, 推荐机型 key 列表, 错误)；评测统一取前 20 台，忽略 LLM 给的 top_k。"""
    args = next((args for name, args in calls if name == RECOMMEND), None)
    if args is None:
        return None, [], None
    if not isinstance(args, dict):
        return args, [], "参数不是 JSON 对象"
    if unknown := sorted(set(args) - {"conditions", "preference", "top_k"}):
        return args, [], f"未知字段：{'、'.join(unknown)}"  # 与接口一致，条件平铺到顶层时报错
    try:
        return args, recommender.keys(args.get("conditions", {}), args.get("preference", "")), None
    except ValidationError as error:
        return args, [], json.dumps(error.detail, ensure_ascii=False)


def _tool_row(calls, expected):
    """同一轮只调用了应选的工具才算选对；同时调用两个工具算选错。"""
    names = [name for name, _ in calls]
    return {"calls": calls, "tools": names, "tool_ok": bool(names) and set(names) == {expected}}


def spec_rows(queries, corpus, recommender, model):
    rows = []
    for item in queries:
        calls = model.tool_calls([{"role": "user", "content": item["q"]}])
        row = {"id": item["id"], "cat": item["cat"], "q": item["q"],
               **_tool_row(calls, RECOMMEND if item["cat"] == "D" else SEARCH)}
        if item["cat"] == "D":
            args, order, error = recommend_with(recommender, calls)
            grades = {corpus.contexts[cid].title: g for cid, g in grades_of(item, corpus).items()}
            row.update(args=args, error=error, top5=order[:5], **set_metrics(order, grades))
            if "constraints" in item:
                row["diff"] = condition_diff(to_conditions(item["constraints"]), args)
        rows.append(row)
    return rows


def matching_keys(conditions, recommender):
    """满足标准条件的全部机型，范围与推荐服务相同。"""
    scope = SearchScope(VISIBILITIES, recommender.embedder.space_id)
    return {spec.key for spec in match(ProductSpec.objects.filter(review_context__in=scoped_contexts(scope)), conditions)}


def extra_rows(queries, recommender, model):
    rows = []
    for item in queries:
        calls = model.tool_calls(item["messages"])
        row = {"id": item["id"], "q": item["messages"][-1]["content"], **_tool_row(calls, item["tool"])}
        if item["tool"] == RECOMMEND:
            relevant = matching_keys(item["conditions"], recommender)
            assert relevant, f"{item['id']} 的标准条件没有符合的机型"
            args, order, error = recommend_with(recommender, calls)
            row.update(args=args, error=error, top5=order[:5], diff=condition_diff(item["conditions"], args),
                       **set_metrics(order, dict.fromkeys(relevant, 2)))
        rows.append(row)
    return rows


def _print_metrics(label, rows):
    print(f"-- {label}（n={len(rows)}）P@5={mean(r['p@5'] for r in rows):.3f} nDCG@5={mean(r['ndcg@5'] for r in rows):.3f}")


def _print_conditions(rows):
    for r in rows:
        if r["args"] is None:
            status = "未调用推荐"
        elif r["error"]:
            status = "参数错误 " + r["error"]
        else:
            status = json.dumps(r["diff"], ensure_ascii=False) if r["diff"] else "一致"
        print(f"{r['id']} {status} | {r['q']} -> {json.dumps(r['args'], ensure_ascii=False)}")
    print(f"-- 一致 {sum(r['args'] is not None and not r['diff'] and not r['error'] for r in rows)}/{len(rows)} 条；"
          f"参数错误 {sum(bool(r['error']) for r in rows)} 条")


def print_report(meta, spec, extra, chain):
    print(f"模型 {meta['model']}；工具定义 sha256 {meta['tools_sha256'][:12]}；补充样例 {meta['extra_version']}\n")
    print("== 工具选择")
    by_cat = defaultdict(list)
    for r in spec:
        by_cat[r["cat"]].append(r["tool_ok"])
    print(" ".join(f"{cat}:{sum(oks)}/{len(oks)}" for cat, oks in sorted(by_cat.items())))
    print(f"-- 全部 {sum(r['tool_ok'] for r in spec)}/{len(spec)}；选错：" +
          ("；".join(f"{r['id']} {r['q']} -> {r['tools'] or '直接回答'}" for r in spec if not r["tool_ok"]) or "无"))

    print("\n== 条件换算：D 类 LLM 原子条件与标准条件的差异 {条件名: [标准值, LLM 值]}")
    _print_conditions([r for r in spec if "diff" in r])

    print("\n== 端到端：D 类按 LLM 参数推荐")
    for r in spec:
        if r["cat"] == "D":
            print(f"{r['id']} P@5={r['p@5']:.2f} nDCG@5={r['ndcg@5']:.2f} | {r['q']} -> {r['top5']}")
    _print_metrics("LLM，D 类全部（与 v17 对比）", [r for r in spec if r["cat"] == "D"])
    _print_metrics("LLM，有标准条件的查询（与链路对比）", [r for r in spec if "diff" in r])
    _print_metrics("链路", chain)

    print("\n== 补充样例：口语化与多轮追问")
    print(f"-- 工具选择 {sum(r['tool_ok'] for r in extra)}/{len(extra)}；选错：" +
          ("；".join(f"{r['id']} -> {r['tools'] or '直接回答'}" for r in extra if not r["tool_ok"]) or "无"))
    recommend_rows = [r for r in extra if "diff" in r]
    _print_conditions(recommend_rows)
    _print_metrics("按 LLM 参数推荐", recommend_rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path, help="召回评测查询集")
    parser.add_argument("extra", type=Path, help="补充样例（口语化与多轮追问）")
    parser.add_argument("out", type=Path, help="结果 JSON 输出路径")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    extra = json.loads(args.extra.read_text(encoding="utf-8"))
    corpus = load_corpus(spec, args.spec.parent)
    recommender = Recommender()
    model = ChatModel(*load_tools())
    result = {"meta": {"model": model.model, "extra_version": extra["version"],
                       "tools_sha256": hashlib.sha256(TOOL_FILE.read_bytes()).hexdigest()},
              "spec": spec_rows(spec["queries"], corpus, recommender, model),
              "extra": extra_rows(extra["queries"], recommender, model),
              "chain": chain_rows(spec["queries"], corpus, recommender)}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print_report(**result)


if __name__ == "__main__":
    main()
