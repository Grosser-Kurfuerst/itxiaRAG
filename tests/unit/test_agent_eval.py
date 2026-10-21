"""只检查判分契约与执行边界，所有网络调用替换为明确替身。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest


@pytest.fixture
def evaluator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "eval"))
    import agent_eval
    return agent_eval


@pytest.fixture
def item():
    return {"id": "D01", "q": "五千以内推荐一台", "cat": "D", "needs": [{"id": "selection", "answer": "符合预算"}],
            "agent": {"mode": "recommend"}}


@pytest.fixture
def judgement():
    return {"needs": [{"id": "selection", "status": "full", "answer_quote": "推荐A"}],
            "recommended_keys": ["A"], "unsupported_claims": [], "errors": []}


def test_verdict_requires_complete_and_grounded_answer(evaluator, item, judgement):
    gold = {"allowed_products": [{"key": "A"}]}
    assert evaluator.verdict(item, ["推荐A"], judgement, gold)["task_pass"]
    judgement["unsupported_claims"] = [{"claim": "十年质保"}]
    assert not evaluator.verdict(item, ["推荐A"], judgement, gold)["task_pass"]
    judgement["unsupported_claims"] = []
    judgement["needs"][0]["status"] = "partial"
    assert evaluator.verdict(item, ["推荐A"], judgement, gold)["coverage"] == 0


def test_budget_violation_is_checked_against_independent_allowed_set(evaluator, item, judgement):
    result = evaluator.verdict(item, ["推荐A"], judgement, {"allowed_products": [{"key": "B"}]})
    assert not result["task_pass"] and result["rule_errors"]


def test_judge_cannot_invent_answer_quotes_or_drop_requirements(evaluator, item, judgement):
    with pytest.raises(ValueError, match="引用不在"):
        evaluator.verdict(item, ["我不知道"], judgement, {})
    judgement["needs"] = []
    with pytest.raises(ValueError, match="id"):
        evaluator.verdict(item, ["推荐A"], judgement, {})


def test_no_answer_and_incomplete_answer_are_different(evaluator, item, judgement):
    item["agent"]["mode"] = "no_answer"
    judgement["needs"][0]["answer_quote"] = "没有对应资料"
    assert evaluator.verdict(item, ["没有对应资料"], judgement, {})["task_pass"]
    judgement["needs"][0]["status"] = "missing"
    assert not evaluator.verdict(item, ["没有对应资料"], judgement, {})["task_pass"]


def test_execution_uses_real_previous_answers_and_distinct_sessions(evaluator, monkeypatch, item):
    item["agent"]["turns"] = ["第一台能扩内存吗"]
    records, incoming = [], []

    def fake_request(url, body=None, **kwargs):
        if url.endswith("/inject"):
            incoming.append(body)
            records.append({"Request": {"Target": {"UserID": body["user_id"]}, "Message": {
                "Segments": [{"Type": "text", "Data": {"text": "推荐A"}}]}}})
            return {}
        # 真正 mock 适配器的新宿主在尚未发送消息时序列化 nil slice，返回 null。
        return deepcopy(records) if records else None

    monkeypatch.setattr(evaluator, "request_json", fake_request)
    proxy = SimpleNamespace(lock=threading.Lock(), active=None)
    result = evaluator.execute(item, "http://mock", proxy, 1, "run")
    assert result["answers"] == ["推荐A", "推荐A"]
    assert [r["text"] for r in incoming] == [item["q"], item["agent"]["turns"][0]]
    assert incoming[0]["user_id"] == incoming[1]["user_id"] == "eval-run-D01"
    assert proxy.active is None


def test_metrics_keep_execution_failures_in_total(evaluator):
    rows = [{"id": "A01", "cat": "A", "split": "dev", "origin": "legacy", "status": "scored",
             "coverage": 1, "task_pass": True},
            {"id": "G01", "cat": "G", "split": "test", "origin": "expanded", "status": "execution_error"}]
    summary = evaluator.summarize(rows)
    assert summary["ALL"]["n"] == 2 and summary["ALL"]["scored"] == 1
    assert summary["ALL"]["task_pass_rate"] == 1
    assert summary["ALL"]["effective_pass_rate"] == 0.5
    assert summary["split:test"]["coverage"] is None


def test_missing_spec_values_never_meet_hard_constraints(evaluator):
    assert not evaluator.matches_spec({"battery_hours": None}, {"battery_min": 10})
    assert not evaluator.matches_spec({"price_cny": 5001}, {"price": [None, 5000]})
    assert evaluator.matches_spec({"price_cny": 5000}, {"price": [None, 5000]})


def test_judge_only_sees_actual_tool_messages_without_repeated_history(evaluator):
    tool = {"role": "tool", "content": "实际截断后正文", "tool_call_id": "first"}
    trace = [{"request": {"messages": [{"role": "system", "content": "提示词"}, tool]},
              "response": {"unseen": "尚未送入下一次模型调用的内容"}},
             {"request": {"messages": [tool, {"role": "tool", "content": "第二段", "tool_call_id": "second"}]}}]
    assert evaluator.visible_tools(trace) == [tool, trace[1]["request"]["messages"][1]]


def test_rejudging_preserves_execution_model_and_budgets(evaluator):
    recorded = {"metadata": {"agent_model": "executed-A", "judge_model": "old-judge", "runtime": "persona-mock",
                            "runtime_config_sha256": "original", "budgets": {"reply_max_chars": 500},
                            "cases_sha256": "original-cases"}}
    metadata = evaluator.execution_metadata(recorded, {"MODEL": "configured-B"}, {"MODEL": "new-judge"}, {}, [], [])
    assert metadata["agent_model"] == "executed-A"
    assert metadata["budgets"] == {"reply_max_chars": 500}
    assert metadata["runtime_config_sha256"] == "original"
    assert metadata["judge_model"] == "new-judge"
    assert metadata["execution_cases_sha256"] == "original-cases"


def test_rejudge_accepts_label_revision_but_rejects_changed_user_inputs(evaluator, item):
    old = {"queries": [deepcopy(item)]}
    record = {"metadata": {"cases_sha256": evaluator.digest(old)}}
    item["needs"][0]["answer"] = "修正标准条件"
    evaluator.check_recorded_cases(record, old, [item])
    item["agent"]["turns"] = ["新增追问"]
    with pytest.raises(ValueError, match="问题或追问"):
        evaluator.check_recorded_cases(record, old, [item])


def test_timeout_stops_batch_before_another_case_can_receive_late_requests(evaluator, item, monkeypatch, tmp_path):
    import json
    import sys

    case_b = {**item, "id": "D02", "q": "换一个预算"}
    spec = {"aliases": {}, "queries": [item, case_b], "specs": "products.json"}
    (tmp_path / "cases.json").write_text(json.dumps(spec))
    (tmp_path / "products.json").write_text("[]")
    (tmp_path / "corpus.json").write_text("[]")
    calls = []

    def timeout(*args):
        calls.append(args[0]["id"])
        raise TimeoutError("late")

    class Proxy:
        events = {}

        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(evaluator, "execute", timeout)
    monkeypatch.setattr(evaluator, "ModelProxy", Proxy)
    monkeypatch.setattr(evaluator, "model_config", lambda prefix: {"BASE_URL": "http://fake", "MODEL": "fake"})
    monkeypatch.setattr(sys, "argv", ["agent_eval", str(tmp_path / "cases.json"), str(tmp_path / "out.json"),
                                      "--corpus", str(tmp_path / "corpus.json")])
    evaluator.main()
    result = json.loads((tmp_path / "out.json").read_text())
    assert calls == ["D01"]
    assert [r["status"] for r in result["rows"]] == ["execution_error", "not_run"]
    assert not result["metadata"]["complete"]
