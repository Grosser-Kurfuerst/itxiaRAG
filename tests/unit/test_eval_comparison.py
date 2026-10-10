from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture
def comparison(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "eval"))
    import compare_runs
    return compare_runs


@pytest.fixture
def rows():
    return {"T01": {"q": "如何恢复文件", "cat": "T", "rel": ["答案"], "facts": [],
                    "top5": ["答案", "旧父段"], "ranks": {"hybrid": 1}}}


def test_comparison_reports_new_unlabeled_parent_when_answer_rank_is_unchanged(comparison, rows):
    after = deepcopy(rows)
    after["T01"]["top5"] = ["答案", "新父段"]
    assert comparison.changes(rows, after)[1] == []
    assert len(comparison.new_unlabeled(rows, after)) == 1
    assert "新父段" in comparison.new_unlabeled(rows, after)[0]


def test_comparison_rejects_results_from_different_annotations(comparison, rows):
    after = deepcopy(rows)
    after["T01"]["rel"].append("新答案")
    with pytest.raises(AssertionError, match="同一标注重跑"):
        comparison.validate_queries(rows, after)


def test_comparison_marks_loss_of_first_place_and_top_five(comparison, rows):
    after = deepcopy(rows)
    after["T01"]["ranks"]["hybrid"] = None
    title, changes = comparison.changes(rows, after)
    assert title == "变差 1 条，变好 0 条"
    assert "跌出前5" in changes[0] and "丢失第1名" in changes[0]
