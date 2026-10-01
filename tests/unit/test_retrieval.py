from uuid import UUID

import pytest

from contracts.errors import DomainError
from contracts.types import Candidate
from embeddings.validation import validate_vectors
from retrieval.hybrid import HybridRetriever, RRFRanker
from retrieval.keyword import terms
from retrieval.vector import cosine


def test_rrf_uses_ranks_merges_routes_and_does_not_double_count():
    a, b, c, parent = [UUID(int=i) for i in range(1, 5)]
    keyword = [Candidate(a, parent, 999, {'keyword': 1}), Candidate(b, parent, 1, {'keyword': 2})]
    vector = [Candidate(b, parent, .99, {'vector': 1}), Candidate(c, parent, .98, {'vector': 2})]
    result = RRFRanker().rank('q', [keyword, vector, keyword])
    assert [row.evidence_id for row in result] == [b, a, c]
    assert result[0].score == pytest.approx(1/62 + 1/61)
    assert result[0].ranks == {'keyword': 2, 'vector': 1}
    assert result[1].score == pytest.approx(1/61)


def test_hybrid_passes_identical_scope_to_replaceable_retrievers():
    from unittest.mock import Mock
    left, right, scope = Mock(), Mock(), object()
    left.search.return_value = right.search.return_value = []
    assert HybridRetriever([left, right], RRFRanker()).search('q', scope, 20) == []
    left.search.assert_called_once_with('q', scope, 20)
    right.search.assert_called_once_with('q', scope, 20)


def test_keyword_and_cosine_basics():
    assert terms('A14-2025，WIN_11？win_11') == ['A14-2025', 'WIN_11']
    assert terms('电脑很卡') == ['电脑很卡']
    assert cosine([1, 0], [5, 0]) == 1
    assert cosine([1, 0], [0, 1]) == 0


@pytest.mark.parametrize('vectors', [[[0, 0]], [[float('nan'), 1]], [[1]], [], [[True, 0]]])
def test_bad_vectors_are_rejected(vectors):
    with pytest.raises(DomainError):
        validate_vectors(vectors, 1, 2)
