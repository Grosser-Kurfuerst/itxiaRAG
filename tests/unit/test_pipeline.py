from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from contracts.types import Candidate, ContextBatch, EvidenceBatch, RouteBatch, SearchRequest, SearchScope
from retrieval.pipeline import PostRecallPipeline
from retrieval.steps import GroupParentsStep, RRFFusionStep, TopKParentsStep


@pytest.fixture
def request_data():
    return SearchRequest('续航', SearchScope(('public',), 'test-space'), top_k=2)


@pytest.fixture
def routes():
    return RouteBatch({'vector': [
        Candidate(UUID(int=1), UUID(int=10), .9, {'vector': 1}, {'vector': .9}, 'cosine'),
        Candidate(UUID(int=2), UUID(int=20), .8, {'vector': 2}, {'vector': .8}, 'cosine'),
        Candidate(UUID(int=3), UUID(int=10), .7, {'vector': 3}, {'vector': .7}, 'cosine'),
    ]})


class ReverseEvidence:
    input_stage = output_stage = 'evidence'

    def process(self, request, batch):
        return EvidenceBatch(list(reversed(batch.candidates)))


class DropFirstEvidence:
    input_stage = output_stage = 'evidence'

    def process(self, request, batch):
        return EvidenceBatch(batch.candidates[1:])


def run(request, routes, *extra):
    return PostRecallPipeline([
        RRFFusionStep(), *extra, GroupParentsStep(), TopKParentsStep(),
    ]).run(request, routes)


def test_composition_root_uses_settings_unless_overridden(request_data, routes, settings):
    from config import components
    settings.RETRIEVAL_RRF_K, settings.RETRIEVAL_RRF_WEIGHTS = 60, {}
    assert components.post_recall_pipeline().run(request_data, routes).contexts[0].score == pytest.approx(1/61)
    custom = components.post_recall_pipeline(rrf_k=10, rrf_weights={'vector': 2})
    assert custom.run(request_data, routes).contexts[0].score == pytest.approx(2/11)


def test_default_pipeline_groups_without_summing_scores_and_limits_parents(request_data, routes):
    result = run(request_data, routes)
    assert [parent.context_id.int for parent in result.contexts] == [10, 20]
    parent = result.contexts[0]
    assert [match.evidence_id.int for match in parent.matches] == [1, 3]
    assert parent.score == pytest.approx(1/61) and parent.score_kind == 'rrf'
    assert parent.matches[0].route_scores == {'vector': .9}
    assert run(replace(request_data, top_k=1), routes).contexts == result.contexts[:1]


def test_insert_remove_and_reorder_steps_changes_results_without_mutating_input(request_data, routes):
    filtered = run(request_data, routes, DropFirstEvidence())
    assert [parent.context_id.int for parent in filtered.contexts] == [20, 10]
    reverse_after_filter = run(request_data, routes, DropFirstEvidence(), ReverseEvidence())
    filter_after_reverse = run(request_data, routes, ReverseEvidence(), DropFirstEvidence())
    assert [parent.context_id.int for parent in reverse_after_filter.contexts] == [10, 20]
    assert [parent.context_id.int for parent in filter_after_reverse.contexts] == [20, 10]
    assert [parent.context_id.int for parent in run(request_data, routes).contexts] == [10, 20]
    assert [item.evidence_id.int for item in routes.routes['vector']] == [1, 2, 3]
    assert routes.routes['vector'][0].score == .9


def test_empty_routes_remain_typed_until_final_contexts(request_data):
    assert run(request_data, RouteBatch({'keyword': [], 'vector': []})) == ContextBatch([])


@pytest.mark.parametrize('steps', [
    [], [GroupParentsStep(), RRFFusionStep()],
    [RRFFusionStep()],
    [RRFFusionStep(), GroupParentsStep(), ReverseEvidence()],
])
def test_pipeline_rejects_incompatible_or_incomplete_configuration(steps):
    with pytest.raises(ValueError):
        PostRecallPipeline(steps)


def test_pipeline_checks_step_output_and_propagates_failures(request_data, routes):
    class WrongOutput:
        input_stage = output_stage = 'evidence'

        def process(self, request, batch):
            return RouteBatch({})

    with pytest.raises(TypeError, match='返回了错误批次阶段'):
        run(request_data, routes, WrongOutput())

    class FailedStep(ReverseEvidence):
        def process(self, request, batch):
            raise RuntimeError('step failed')

    with pytest.raises(RuntimeError, match='step failed'):
        run(request_data, routes, FailedStep())


def test_parent_steps_can_reorder_and_final_output_still_honors_top_k(request_data, routes):
    class ReverseParents:
        input_stage = output_stage = 'contexts'

        def process(self, request, batch):
            return ContextBatch(list(reversed(batch.contexts)))

    pipeline = PostRecallPipeline([RRFFusionStep(), GroupParentsStep(), ReverseParents()])
    result = pipeline.run(replace(request_data, top_k=1), routes)
    assert [parent.context_id.int for parent in result.contexts] == [20]


def test_query_and_scope_are_read_only_for_steps(request_data):
    with pytest.raises(FrozenInstanceError):
        request_data.scope = SearchScope(('internal',), 'test-space')
    with pytest.raises(FrozenInstanceError):
        request_data.scope.visibilities = ('internal',)
