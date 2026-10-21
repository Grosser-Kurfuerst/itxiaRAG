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
