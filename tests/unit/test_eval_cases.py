from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture
def cases(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "eval"))
    import cases
    return cases


@pytest.fixture
def spec():
    return {"aliases": {"型号": "电脑"}, "queries": [{"id": "A01", "cat": "A", "q": "内存能换吗", "rel": ["型号"],
             "group": "电脑内存", "split": "dev", "needs": [{"id": "memory", "answer": "板载不能换",
             "evidence": [{"ref": "型号", "quote": "板载不能换"}]}]}]}


def test_evidence_must_exist_in_target_parent(cases, spec):
    contexts = [{"title": "电脑", "body": "板载 不能换", "source": {"schema": "product_review"}}]
    assert cases.validate(spec, contexts)["queries"] == 1
    contexts[0]["body"] = "能换"
    with pytest.raises(AssertionError, match="原文不存在"):
        cases.validate(spec, contexts)


def test_fact_variants_cannot_cross_dev_test(cases, spec):
    other = deepcopy(spec["queries"][0])
    other.update(id="B01", cat="B", q="简称内存能换吗", split="test")
    spec["queries"].append(other)
    with pytest.raises(AssertionError, match="分组跨集合"):
        cases.validate(spec)


def test_case_ids_and_need_ids_are_unique(cases, spec):
    spec["queries"][0]["needs"].append(spec["queries"][0]["needs"][0])
    with pytest.raises(AssertionError, match="重复需求"):
        cases.validate(spec)


def test_g_type_is_required_only_for_unanswerable_cases(cases, spec):
    spec["queries"].append({"id": "G01", "cat": "G", "q": "不存在的机型多重", "rel": [],
                            "needs": [{"id": "boundary", "answer": "说明没有资料", "evidence": []}]})
    with pytest.raises(AssertionError, match="g_type"):
        cases.validate(spec)
    spec["queries"][1]["g_type"] = "near_model"
    assert cases.validate(spec)["queries"] == 2
    spec["queries"][0]["g_type"] = "near_model"
    with pytest.raises(AssertionError, match="g_type"):
        cases.validate(spec)


def test_expanded_questions_reject_source_jargon(cases, spec):
    spec["queries"][0].update(origin="expanded", q="满载人位噪音多少")
    with pytest.raises(AssertionError, match="原文术语"):
        cases.validate(spec, recall_full=True)


def test_expanded_x_cases_must_combine_documents_and_vary_tutorials(cases, spec):
    spec["aliases"]["教程"] = {"doc": "help/guide"}
    x = {"id": "X01", "cat": "X", "q": "怎么加内存", "rel": ["型号", "教程"], "group": "X01", "split": "dev",
         "origin": "expanded", "needs": [deepcopy(spec["queries"][0]["needs"][0])]}
    spec["queries"] = [x]
    with pytest.raises(AssertionError, match="跨文档"):
        cases.validate(spec, recall_full=True)
    x["needs"].append({"id": "install", "answer": "斜插下压", "evidence": [{"ref": "教程", "quote": "斜插下压"}]})
    spec["queries"] = [deepcopy(x) | {"id": f"X0{i}", "q": f"怎么加内存{i}", "group": f"X0{i}"} for i in range(1, 6)]
    with pytest.raises(AssertionError, match="教程复用过多"):
        cases.validate(spec, recall_full=True)
