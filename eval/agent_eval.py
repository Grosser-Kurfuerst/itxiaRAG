"""通过真实 persona 的 mock HTTP 适配器评测答案；本地模型代理记录实际可见工具消息。

宿主 llm_base_url 指向 http://127.0.0.1:<proxy-port>/v1；代理只转发到 EVAL_LLM_BASE_URL。
EVAL_JUDGE_* 未配置时显式复用 EVAL_LLM_*。运行与宿主配置见 docs/phase1/evaluation-expansion.md。
"""
import argparse
import json
import os
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import mean
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cases import contains, digest, resolve, validate

JUDGE_FILE = Path(__file__).with_name("agent-judge.md")


def request_json(url, body=None, headers=None, timeout=180):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "itxia-eval",
                                            **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def model_config(prefix):
    return {key: os.environ.get(prefix + key, os.environ.get("EVAL_LLM_" + key, ""))
            for key in ("BASE_URL", "MODEL", "API_KEY")}


class ModelProxy:
    """顺序运行用例；执行异常后整批停止，避免宿主晚到的后续请求串入下一题。"""
    def __init__(self, port, config):
        self.config, self.active, self.events, self.lock = config, None, {}, threading.Lock()
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                with proxy.lock:
                    case_id = proxy.active
                if case_id is None:
                    self.send_error(503)
                    return
                event = {}
                try:
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    event["request"] = body
                    headers = {"Authorization": "Bearer " + config["API_KEY"]} if config["API_KEY"] else {}
                    result = request_json(config["BASE_URL"].rstrip("/") + "/chat/completions", body, headers)
                    event["response"] = result
                    payload = json.dumps(result, ensure_ascii=False).encode()
                    status = 200
                except Exception as error:
                    status = error.code if isinstance(error, HTTPError) else 502
                    event["error"] = f"model_proxy:{type(error).__name__}:{status}"
                    payload = json.dumps({"error": {"message": event["error"]}}).encode()
                with proxy.lock:
                    proxy.events.setdefault(case_id, []).append(event)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def sent_text(record):
    message = record["Request"]["Message"]
    return "".join(s.get("Data", {}).get("text", "") for s in message.get("Segments", [])
                   if s.get("Type") == "text")


def execute(item, persona_url, proxy, timeout, run_id, progress=None):
    user = f"eval-{run_id}-{item['id']}"
    answers, trace_ends, started = [], [], time.monotonic()
    if progress is not None:
        progress.update(answers=answers, trace_ends=trace_ends)
    with proxy.lock:
        proxy.active = item["id"]
    try:
        for turn in [item["q"], *item["agent"].get("turns", [])]:
            before = len(request_json(persona_url + "/sent") or [])
            request_json(persona_url + "/inject", {"kind": "private", "text": turn,
                                                  "user_id": user, "user_name": "评测用户"})
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                records = (request_json(persona_url + "/sent") or [])[before:]
                own = [r for r in records if r["Request"]["Target"].get("UserID") == user]
                if own:
                    if any(r.get("Err") for r in own):
                        raise ValueError("宿主发送失败")
                    answer = "\n".join(sent_text(r) for r in own)
                    if not answer.strip():
                        raise ValueError("宿主发送的答案为空")
                    answers.append(answer)
                    with proxy.lock:
                        trace_ends.append(len(proxy.events.get(item["id"], [])))
                    break
                with proxy.lock:
                    if any("error" in event for event in proxy.events.get(item["id"], [])):
                        raise ValueError("模型接口调用失败；停止等待宿主答复")
                time.sleep(0.2)
            else:
                raise TimeoutError("persona 未在预算内发送答案")
        return {"status": "generated", "answers": answers, "trace_ends": trace_ends, "elapsed_seconds": round(time.monotonic() - started, 3)}
    finally:
        if progress is not None:
            progress["elapsed_seconds"] = round(time.monotonic() - started, 3)
        with proxy.lock:
            proxy.active = None


def matches_spec(record, constraints):
    """独立标准条件对静态规格表求集合，不借用本次工具返回作为 gold。"""
    for key, value in constraints.items():
        if key == "price":
            x = record.get("price_cny")
            ok = x is not None and (value[0] is None or x >= value[0]) and (value[1] is None or x <= value[1])
        elif key in ("weight_max", "thin_light", "screen_min", "battery_min"):
            field, bound, lower = {"weight_max": ("weight_kg", value, False),
                                   "thin_light": ("weight_kg", 1.5, False),
                                   "screen_min": ("screen_inch", value, True),
                                   "battery_min": ("battery_hours", value, True)}[key]
            x = record.get(field)
            ok = x is not None and (x >= bound if lower else x <= bound)
        elif key == "gpu":
            ok = record.get("gpu") in value
        elif key in ("ports", "ports_rich"):
            ports = value if key == "ports" else ("usb_a", "usb_c", "video_out")
            ok = all(record["ports"].get(p) for p in ports)
        elif key == "oled":
            ok = record.get("panel") is not None and (record["panel"] == "oled") == value
        elif key == "gaming":
            ok = record.get("is_gaming") == value
        else:
            raise ValueError(f"未知标准条件: {key}")
        if not ok:
            return False
    return True


def gold_for(item, spec, contexts, products):
    evidence = []
    for need in item["needs"]:
        for e in need.get("evidence", []):
            parents = resolve(spec["aliases"][e["ref"]], contexts)
            source = next(c["source"] for c in parents if contains(c["body"], e["quote"]))
            evidence.append({**e, "need": need["id"], "source_url": source["url"], "source_title": source["title"]})
    gold = {"evidence": evidence}
    if item["cat"] == "D":
        if "constraints" in item:
            allowed = [p for p in products if matches_spec(p, item["constraints"])]
        else:
            names = {spec["aliases"][a] for a in item.get("rel", []) if isinstance(spec["aliases"][a], str)}
            allowed = [p for p in products if p["key"] in names]
        gold["allowed_products"] = allowed
    return gold


def verdict(item, answers, judgement, gold):
    for key in ("needs", "errors", "unsupported_claims", "recommended_keys"):
        if not isinstance(judgement[key], list):
            raise ValueError(f"评审 {key} 必须为列表")
    needs = judgement["needs"]
    expected = {n["id"] for n in item["needs"]}
    if len(needs) != len(expected) or {n["id"] for n in needs} != expected:
        raise ValueError("评审 need id 不完整或重复")
    for n in needs:
        if n["status"] not in ("full", "partial", "missing"):
            raise ValueError("非法要点状态")
        if n["status"] == "full" and not any(contains(a, n["answer_quote"]) for a in answers):
            raise ValueError("评审引用不在用户实际收到的答案中")
    errors = list(judgement["errors"])
    if item["agent"].get("mode") == "recommend":
        allowed = {p["key"] for p in gold.get("allowed_products", [])}
        selected = judgement["recommended_keys"]
        if set(selected) - allowed:
            errors.append("推荐了不满足标准条件或身份不明的机型")
        if allowed and not selected:
            errors.append("没有推荐可用机型")
    coverage = sum(n["status"] == "full" for n in needs) / len(needs)
    return {"coverage": coverage, "task_pass": coverage == 1 and not errors and not judgement["unsupported_claims"],
            "rule_errors": errors}


def visible_tools(trace):
    """只取真正送入模型的工具消息；去除后续轮次重复携带的历史。"""
    messages, seen = [], set()
    for event in trace:
        for message in event.get("request", {}).get("messages", []):
            if message.get("role") == "tool" and digest(message) not in seen:
                seen.add(digest(message))
                messages.append(message)
    return messages


def judge(item, result, gold, config):
    body = {"model": config["MODEL"], "temperature": 0,
            "messages": [{"role": "system", "content": JUDGE_FILE.read_text()},
                         {"role": "user", "content": json.dumps({"case": item, "gold": gold,
                          "visible_tools": visible_tools(result["trace"]), "answers": result["answers"],
                          "conversation": result.get("conversation", [])}, ensure_ascii=False)}]}
    headers = {"Authorization": "Bearer " + config["API_KEY"]} if config["API_KEY"] else {}
    response = request_json(config["BASE_URL"].rstrip("/") + "/chat/completions", body, headers)
    raw = response["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    judgement = json.loads(raw)
    return {"judgement": judgement, "judge_usage": response.get("usage")}



def turn_item(item, index):
    """每轮使用自己的验收点及累计硬条件，不向评委暴露未来追问。"""
    active = {**item, "agent": {k: v for k, v in item["agent"].items() if k not in ("turns", "turn_checks")}}
    if index:
        active.update(item["agent"]["turn_checks"][index - 1])
        active["q"] = item["agent"]["turns"][index - 1]
    return active


def assess_turns(item, result, spec, contexts, products, config):
    answers, trace = result["answers"], result["trace"]
    if len(answers) != 1 + len(item["agent"].get("turns", [])):
        raise ValueError("实际答复数与用例轮数不符")
    ends = result.get("trace_ends", [len(trace)] if len(answers) == 1 else [])
    if len(ends) != len(answers) or ends != sorted(ends) or not ends or ends[0] < 1 or ends[-1] != len(trace):
        raise ValueError("缺少有效的逐轮工具证据边界")
    turns, conversation = result.setdefault("turn_results", []), []
    for i, (answer, end) in enumerate(zip(answers, ends)):
        active = turn_item(item, i)
        gold = gold_for(active, spec, contexts, products)
        assessment = judge(active, {"answers": [answer], "trace": trace[:end],
                                    "conversation": conversation}, gold, config)
        assessment["trace_end"] = end
        turns.append(assessment)  # 即使引用校验失败，也保留评委原始输出。
        assessment.update(verdict(active, [answer], assessment["judgement"], gold))
        conversation.append({"user": active["q"], "answer": answer})
    return {"turn_results": turns, "turn_count": len(turns),
            "coverage": mean(t["coverage"] for t in turns), "task_pass": all(t["task_pass"] for t in turns)}

def summarize(rows):
    groups = {"ALL": rows}
    for key in ("cat", "split", "origin"):
        for value in sorted({r[key] for r in rows}):
            groups[f"{key}:{value}"] = [r for r in rows if r[key] == value]
    for label, multiple in (("single", False), ("multi", True)):
        groups[label] = [r for r in rows if (r.get("turn_count", 1) > 1) == multiple]
    summary = {}
    for name, sub in groups.items():
        scored = [r for r in sub if r["status"] == "scored"]
        summary[name] = {"n": len(sub), "scored": len(scored), "status": dict(Counter(r["status"] for r in sub)),
                         "coverage": mean(r["coverage"] for r in scored) if scored else None,
                         "passed": sum(r.get("task_pass", False) for r in sub),
                         "task_pass_rate": sum(r["task_pass"] for r in scored) / len(scored) if scored else None,
                         "effective_pass_rate": sum(r.get("task_pass", False) for r in sub) / len(sub) if sub else None,
                         "incomplete": sum(r["coverage"] < 1 for r in scored),
                         "unsupported": sum(any(t["judgement"]["unsupported_claims"] for t in r.get("turn_results", [])) for r in scored),
                         "rule_errors": sum(any(t["rule_errors"] for t in r.get("turn_results", [])) for r in scored)}
    return summary


def execution_metadata(recorded, model, assessor, spec, contexts, products):
    metadata = dict(recorded["metadata"]) if recorded else {
        "started_at": datetime.now(timezone.utc).isoformat(), "runtime": "persona-mock",
        "agent_model": model["MODEL"], "cases_sha256": digest(spec),
        "corpus_sha256": digest(contexts), "specs_sha256": digest(products)}
    metadata.update(judge_protocol="per-turn-v2", judge_model=assessor["MODEL"], judge_sha256=digest(JUDGE_FILE.read_text()),
                    judged_at=datetime.now(timezone.utc).isoformat(), complete=False)
    if recorded:
        metadata["recorded_sha256"] = digest(recorded)
        metadata.setdefault("execution_cases_sha256", recorded["metadata"]["cases_sha256"])
        metadata["cases_sha256"] = digest(spec)
    return metadata


def check_recorded_cases(recorded, original, current):
    if recorded["metadata"]["cases_sha256"] != digest(original):
        raise ValueError("记录与原用例快照不一致")
    old = {q["id"]: q for q in original["queries"]}
    for q in current:
        previous = old[q["id"]]
        if (q["q"], q["agent"].get("turns", [])) != (previous["q"], previous["agent"].get("turns", [])):
            raise ValueError(f"重评不能改变实际执行的问题或追问: {q['id']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--persona-url", default="http://127.0.0.1:18080")
    parser.add_argument("--proxy-port", type=int, default=19091)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--split", choices=("dev", "test"))
    parser.add_argument("--recorded", type=Path, help="仅重评已记录的真实执行，不重复调用 Agent")
    parser.add_argument("--recorded-spec", type=Path, help="修订标注前的用例快照；重评允许改标签，但问题和追问必须相同")
    parser.add_argument("--runtime-config", type=Path, help="实际宿主 YAML；只记录哈希和非敏感预算")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    contexts = json.loads(args.corpus.read_text())
    validate(spec, contexts)
    products = json.loads((args.spec.parent / spec["specs"]).read_text())
    queries = [q for q in spec["queries"] if q.get("agent") and
               (not args.ids or q["id"] in args.ids) and (not args.split or q.get("split", "dev") == args.split)]
    if not queries or (args.ids and set(args.ids) - {q["id"] for q in queries}):
        parser.error("没有匹配的 Agent 用例，或请求的 id 未启用／不在所选集合")
    recorded = json.loads(args.recorded.read_text()) if args.recorded else None
    if args.recorded_spec and not recorded:
        parser.error("--recorded-spec 必须与 --recorded 一起使用")
    if recorded:
        original = json.loads(args.recorded_spec.read_text()) if args.recorded_spec else spec
        try:
            check_recorded_cases(recorded, original, queries)
        except (KeyError, ValueError) as error:
            parser.error(str(error))
    if recorded and (recorded["metadata"]["corpus_sha256"] != digest(contexts) or
                     recorded["metadata"]["specs_sha256"] != digest(products)):
        parser.error("记录与当前语料或规格快照不一致")
    model, assessor = model_config("EVAL_LLM_"), model_config("EVAL_JUDGE_")
    if not assessor["BASE_URL"] or not assessor["MODEL"] or (not recorded and not model["BASE_URL"]):
        parser.error("缺少 EVAL_LLM_* / EVAL_JUDGE_* 模型配置")
    report = {"metadata": execution_metadata(recorded, model, assessor, spec, contexts, products), "rows": []}
    if args.runtime_config:
        import yaml
        if recorded and recorded["metadata"].get("runtime_config_sha256") != digest(args.runtime_config.read_text()):
            parser.error("重评不能声明不同的宿主配置")
        runtime = yaml.safe_load(args.runtime_config.read_text())["plugins"]["persona"]
        report["metadata"]["runtime_config_sha256"] = digest(args.runtime_config.read_text())
        report["metadata"]["budgets"] = {k: runtime.get(k, "runtime_default") for k in (
            "tools_max_rounds", "tools_result_max_chars", "tools_call_timeout", "reply_max_chars", "llm_history_max_chars")}
    run_id = uuid.uuid4().hex[:8]
    stopped = False

    def checkpoint(row):
        report["rows"].append(row)
        report["summary"] = summarize(report["rows"])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
        print(json.dumps({k: row.get(k) for k in ("id", "status", "coverage", "task_pass", "error")},
                         ensure_ascii=False), flush=True)

    with ModelProxy(args.proxy_port, model) as proxy:
        for item in queries:
            row = {"id": item["id"], "cat": item["cat"], "split": item.get("split", "dev"),
                   "origin": "expanded" if item.get("origin") == "expanded" else "legacy",
                   "turn_count": 1 + len(item["agent"].get("turns", []))}
            if stopped:
                row.update(status="not_run", error="先前执行失败；为避免宿主晚到请求污染轨迹，停止本批生成")
                checkpoint(row)
                continue
            try:
                if recorded:
                    previous = next(r for r in recorded["rows"] if r["id"] == item["id"])
                    if not previous.get("answers") or not previous.get("trace"):
                        raise ValueError("没有完整的真实执行记录")
                    row.update({k: previous[k] for k in ("answers", "trace", "elapsed_seconds", "trace_ends") if k in previous})
                else:
                    row.update(execute(item, args.persona_url.rstrip("/"), proxy, args.timeout, run_id, row))
                    row["trace"] = proxy.events.get(item["id"], [])
                    if not row["trace"] or any("error" in e for e in row["trace"]):
                        raise ValueError("模型执行记录缺失或模型接口失败")
                first = row["trace"][0]["request"]
                row["prompt_sha256"] = digest([m for m in first["messages"] if m["role"] == "system"])
                row["schema_sha256"] = digest(first.get("tools", []))
                row["agent_model"] = first["model"]
                if not recorded:
                    report["metadata"]["agent_model"] = first["model"]
            except Exception as error:
                row.update(status="execution_error", error=f"{type(error).__name__}: {error}",
                           trace=proxy.events.get(item["id"], []))
                stopped = not recorded
            else:
                try:
                    row.update(assess_turns(item, row, spec, contexts, products, assessor), status="scored")
                except Exception as error:
                    row.update(status="judge_error", error=f"{type(error).__name__}: {error}")
            checkpoint(row)
    report["metadata"]["complete"] = not any(r["status"] == "not_run" for r in report["rows"])
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
