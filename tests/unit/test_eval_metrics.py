from pathlib import Path

import pytest


@pytest.fixture
def metrics(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'eval'))
    import metrics
    return metrics


def test_precision_uses_actual_return_count_and_recall_full_denominator(metrics):
    result = metrics.set_metrics(list(range(20)), {0: 2})
    assert result['precision'] == 1 / 20
    assert result['recall@10'] == 1
    assert result['ndcg@5'] == 1
    assert metrics.set_metrics(list(range(10)), dict.fromkeys(range(25), 2))['recall@10'] == .4


def test_empty_returns_and_no_positive_labels(metrics):
    assert metrics.set_metrics([], {1: 2})['recall@10'] == 0
    assert metrics.set_metrics([], {})['precision'] == 0
    assert metrics.set_metrics([1], {})['recall@10'] is None


def test_needs_require_all_groups_and_allow_alternative_evidence(metrics):
    needs = [dict(id='support', evidence=[dict(ref='review', quote='可更换')]),
             dict(id='install', evidence=[dict(ref='guide', quote='断电'), dict(ref='other', quote='断开电池')])]
    aliases = {'review': [1], 'guide': [2], 'other': [3]}
    bodies = {1: '内存可更换', 2: '标题包含教程但没有步骤', 3: '先断开电池'}
    assert not metrics.need_coverage(needs, [1, 2], bodies, aliases)['all']
    assert metrics.need_coverage(needs, [1, 3], bodies, aliases)['all']
