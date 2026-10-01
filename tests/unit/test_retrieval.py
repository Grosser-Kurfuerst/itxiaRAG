from uuid import UUID

import pytest

from retrieval.keyword import Candidate, terms
from retrieval.service import aggregate, fit_contexts

pytestmark = pytest.mark.unit


def test_tokenization_preserves_models_and_does_not_invent_chinese_segmentation():
    assert terms(" A14-2025，WIN_11 版本1.2？win_11") == ["A14-2025", "WIN_11", "版本1.2"]
    assert terms("电脑很卡") == ["电脑很卡"]
    assert terms("，？！% _...") == []
    long = " ".join(str(i) for i in range(17))
    assert terms(long) == [long]


def test_parent_ranking_uses_best_child_and_tracks_all_matched_ids():
    a, b, c, p, q = [UUID(int=i) for i in range(1, 6)]
    result = aggregate([Candidate(c, p, "keyword", 3, 10), Candidate(b, q, "keyword", 2, 20), Candidate(a, p, "keyword", 1, 30)])
    assert list(result) == [p, q] and result[p] == [a, c]


def test_budget_skips_whole_parent_then_continues_and_counts_utf8_bytes():
    large, small = {"text": "中" * 100}, {"text": "中"}
    # [{"text":"中"}] 紧凑 UTF-8 为 16 字节。
    selected, incomplete = fit_contexts([large, small], 2, 16)
    assert selected == [small] and incomplete
    assert fit_contexts([small], 1, 15) == ([], True)
