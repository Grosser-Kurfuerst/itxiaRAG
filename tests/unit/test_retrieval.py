from uuid import UUID

import pytest

from contracts.errors import DomainError
from contracts.types import Candidate
from embeddings.validation import validate_vectors
from retrieval.hybrid import MultiRouteRecall, RRFRanker
from retrieval.vector import VectorRetriever, cosine


def test_rrf_uses_ranks_merges_routes_and_does_not_double_count():
    a, b, c, parent = [UUID(int=i) for i in range(1, 5)]
    keyword = [Candidate(a, parent, 999, {'keyword': 1}), Candidate(b, parent, 1, {'keyword': 2})]
    vector = [Candidate(b, parent, .99, {'vector': 1}), Candidate(c, parent, .98, {'vector': 2})]
    result = RRFRanker().rank('q', [keyword, vector, keyword])
    assert [row.evidence_id for row in result] == [b, a, c]
    assert result[0].score == pytest.approx(1/62 + 1/61)
    assert result[0].ranks == {'keyword': 2, 'vector': 1}
    assert result[1].score == pytest.approx(1/61)


def test_rrf_orders_ties_by_stable_key_and_keeps_it():
    a, b, parent = UUID(int=1), UUID(int=2), UUID(int=10)
    # 关键词第 1 名与向量第 1 名的 RRF 分数相同，按稳定键而不是 id 排序。
    keyword = [Candidate(a, parent, 9, {'keyword': 1}, stable_key='s:2')]
    vector = [Candidate(b, parent, .9, {'vector': 1}, stable_key='s:1')]
    result = RRFRanker().rank('q', [keyword, vector])
    assert [row.evidence_id for row in result] == [b, a]
    assert [row.stable_key for row in result] == ['s:1', 's:2']


def test_collector_passes_identical_scope_and_keeps_routes_separate():
    from unittest.mock import Mock
    left, right, scope = Mock(), Mock(), object()
    left.name, right.name = 'keyword', 'vector'
    left.search.return_value = right.search.return_value = []
    assert MultiRouteRecall([left, right]).collect('q', scope, 20).routes == {
        'keyword': [], 'vector': []}
    left.search.assert_called_once_with('q', scope, 20)
    right.search.assert_called_once_with('q', scope, 20)


def test_collector_rejects_duplicate_names_before_searching():
    from unittest.mock import Mock
    left, right = Mock(), Mock()
    left.name = right.name = 'same'
    with pytest.raises(ValueError, match='唯一 name'):
        MultiRouteRecall([left, right])
    left.search.assert_not_called()
    right.search.assert_not_called()


def test_rrf_preserves_scores_for_the_best_rank_of_each_route():
    evidence, parent = UUID(int=1), UUID(int=2)
    worse = Candidate(evidence, parent, .9, {'vector': 3}, {'vector': .9}, 'cosine')
    best = Candidate(evidence, parent, .8, {'vector': 1}, {'vector': .8}, 'cosine')
    keyword = Candidate(evidence, parent, 7, {'keyword': 2}, {'keyword': 7}, 'bm25')
    result = RRFRanker().rank('q', [[worse, best], [keyword], [worse]])[0]
    assert result.ranks == {'vector': 1, 'keyword': 2}
    assert result.route_scores == {'vector': .8, 'keyword': 7}
    assert result.score_kind == 'rrf'
    assert result.score == pytest.approx(1/61 + 1/62)


@pytest.mark.parametrize('threshold, expected', [
    (None, [1, 2, 3, 4]), (-1, [1, 2, 3, 4]),
    (0, [1, 2, 3]), (.6, [1, 2]), (1, [1]),
])
def test_vector_threshold_is_inclusive_and_preserves_raw_scores(threshold, expected):
    from unittest.mock import Mock, patch
    parent, scope = UUID(int=10), object()
    rows = [(UUID(int=i), parent, vector, f'k{i}') for i, vector in enumerate(
        [[1, 0], [.6, .8], [0, 1], [-1, 0]], 1)]
    embedder = Mock()
    embedder.embed_query.return_value = [1, 0]
    with patch('retrieval.vector.scoped_evidence') as scoped:
        scoped.return_value.values_list.return_value.iterator.return_value = rows
        result = VectorRetriever(embedder, min_cosine=threshold).search('q', scope)
    scoped.assert_called_once_with(scope)
    assert [row.evidence_id.int for row in result] == expected
    assert [row.ranks for row in result] == [{'vector': i} for i in range(1, len(result) + 1)]
    assert all(row.route_scores == {'vector': row.score} and row.score_kind == 'cosine'
               for row in result)


@pytest.mark.parametrize('threshold', [-1.01, 1.01, float('nan'), float('inf')])
def test_vector_rejects_invalid_thresholds(threshold):
    with pytest.raises(ValueError, match='min_cosine'):
        VectorRetriever(object(), min_cosine=threshold)


@pytest.mark.parametrize('vector', [[1, 1], [1, 2, 3]])
def test_vector_threshold_one_keeps_non_axis_aligned_identical_vectors(vector):
    from unittest.mock import Mock, patch
    parent, scope = UUID(int=10), object()
    embedder = Mock()
    embedder.embed_query.return_value = vector
    with patch('retrieval.vector.scoped_evidence') as scoped:
        scoped.return_value.values_list.return_value.iterator.return_value = [
            (UUID(int=1), parent, vector, 'k1'),
        ]
        result = VectorRetriever(embedder, min_cosine=1).search('q', scope)
    assert len(result) == 1 and result[0].score == 1
    assert result[0].route_scores == {'vector': 1}


def test_vector_orders_ties_by_stable_key():
    from unittest.mock import Mock, patch
    parent = UUID(int=10)
    embedder = Mock()
    embedder.embed_query.return_value = [1, 0]
    rows = [(UUID(int=1), parent, [1, 0], 's:2'), (UUID(int=2), parent, [2, 0], 's:1')]
    with patch('retrieval.vector.scoped_evidence') as scoped:
        scoped.return_value.values_list.return_value.iterator.return_value = rows
        result = VectorRetriever(embedder).search('q', object())
    assert [row.evidence_id for row in result] == [UUID(int=2), UUID(int=1)]
    assert [row.stable_key for row in result] == ['s:1', 's:2']


def test_cosine_basics():
    assert cosine([1, 0], [5, 0]) == 1
    assert cosine([1, 0], [0, 1]) == 0


@pytest.mark.parametrize('vectors', [[[0, 0]], [[float('nan'), 1]], [[1]], [], [[True, 0]]])
def test_bad_vectors_are_rejected(vectors):
    with pytest.raises(DomainError):
        validate_vectors(vectors, 1, 2)
