from math import log
from unittest.mock import Mock, patch
from uuid import UUID

import pytest

from retrieval.bm25 import bm25_scores
from retrieval.keyword import KeywordRetriever
from retrieval.tokenization import tokenize


def test_tokenizer_splits_chinese_and_preserves_identifiers_and_term_frequency():
    assert tokenize('这台笔记本续航怎么样？') == ['笔记本', '续航']
    assert tokenize('A14-2025，WIN_11？win_11 RTX 4060 USB-C 0x80070005') == [
        'a14-2025', 'win_11', 'win_11', 'rtx', '4060', 'usb-c', '0x80070005']
    assert tokenize('model_1 100%charge model%') == ['model_1', '100%charge', 'model%']
    assert tokenize('C++ C#') == ['c++', 'c#']
    assert tokenize('不能开机，没有声音') == ['不能', '开机', '没有', '声音']
    assert tokenize('？！怎么样') == []


def test_bm25_recalls_a_common_term_even_in_a_single_document():
    assert bm25_scores([['续航']], ['续航']) == pytest.approx([log(4 / 3)])
    scores = bm25_scores([['续航'], ['续航'], ['屏幕']], ['续航'])
    assert scores[0] == scores[1] > 0 and scores[2] == 0
    assert bm25_scores([['续航']], ['续航', '续航']) == bm25_scores([['续航']], ['续航'])


def test_bm25_uses_rarity_saturating_frequency_and_document_length():
    scores = bm25_scores([['续航'], ['屏幕'], ['屏幕']], ['续航', '屏幕'])
    assert scores[0] > scores[1] == scores[2] > 0
    scores = bm25_scores([['续航'], ['续航'] * 2, ['屏幕']], ['续航'], b=0)
    assert scores[0] < scores[1] < 2 * scores[0]
    scores = bm25_scores([['续航'], ['续航'] + ['屏幕'] * 20], ['续航'])
    assert scores[0] > scores[1] > 0


@pytest.mark.parametrize('corpus', [[], [[]], [[], []]])
def test_bm25_handles_empty_corpora(corpus):
    assert bm25_scores(corpus, ['续航']) == [0.0] * len(corpus)
    assert bm25_scores(corpus, []) == [0.0] * len(corpus)


def test_keyword_tokenizer_is_replaceable_and_ranking_precedes_limit():
    scope, parent = object(), UUID(int=10)
    tokenizer = Mock(side_effect=lambda text: text.split())
    rows = [(UUID(int=2), parent, 'battery screen'),
            (UUID(int=1), parent, 'battery'),
            (UUID(int=3), parent, 'keyboard')]
    with patch('retrieval.keyword.scoped_evidence') as scoped:
        scoped.return_value.values_list.return_value = rows
        result = KeywordRetriever(tokenizer).search('battery', scope, 1)
    scoped.assert_called_once_with(scope)
    assert tokenizer.call_count == 4
    assert len(result) == 1 and result[0].evidence_id == UUID(int=1)
    assert result[0].context_id == parent and result[0].ranks == {'keyword': 1}


def test_keyword_excludes_nonmatches_and_orders_ties_by_id():
    parent = UUID(int=10)
    rows = [(UUID(int=2), parent, '续航'), (UUID(int=1), parent, '续航'),
            (UUID(int=3), parent, '屏幕')]
    with patch('retrieval.keyword.scoped_evidence') as scoped:
        scoped.return_value.values_list.return_value = rows
        result = KeywordRetriever().search('续航怎么样', object())
    assert [item.evidence_id for item in result] == [UUID(int=1), UUID(int=2)]
    assert [item.ranks for item in result] == [{'keyword': 1}, {'keyword': 2}]


def test_keyword_empty_query_does_not_read_the_database():
    with patch('retrieval.keyword.scoped_evidence') as scoped:
        assert KeywordRetriever().search('？！', object()) == []
    scoped.assert_not_called()


def test_keyword_threshold_preserves_positive_matches_and_original_scores():
    parent = UUID(int=10)
    rows = [(UUID(int=i), parent, 'battery') for i in range(1, 5)]
    with patch('retrieval.keyword.scoped_evidence') as scoped, \
            patch('retrieval.keyword.bm25_scores', return_value=[0, .4, .8, 1.2]) as scoring:
        scoped.return_value.values_list.return_value = rows
        result = KeywordRetriever(str.split, min_bm25=.8).search('battery', object())
    assert len(scoring.call_args.args[0]) == 4  # 过滤前仍统计完整 Scope 语料。
    assert [item.evidence_id for item in result] == [UUID(int=4), UUID(int=3)]
    assert [item.ranks for item in result] == [{'keyword': 1}, {'keyword': 2}]
    assert [item.route_scores for item in result] == [{'keyword': 1.2}, {'keyword': .8}]
    assert all(item.score_kind == 'bm25' for item in result)


@pytest.mark.parametrize('threshold', [-.1, float('nan'), float('inf')])
def test_keyword_rejects_invalid_thresholds(threshold):
    with pytest.raises(ValueError, match='min_bm25'):
        KeywordRetriever(min_bm25=threshold)
