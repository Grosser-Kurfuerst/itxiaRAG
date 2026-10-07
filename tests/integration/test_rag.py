from copy import deepcopy
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from catalog.models import ContextUnit, EvidenceUnit, KnowledgeSource
from catalog.selectors import DjangoContextReader
from catalog.storage import DjangoDocumentStore
from config import components
from contracts.errors import DomainError
from contracts.query import QuerySerializer
from contracts.serializers import SourceImportSerializer, import_dtos
from contracts.types import SearchScope
from ingestion.pipeline import import_processed
from retrieval.keyword import KeywordRetriever
from retrieval.service import search
from retrieval.pipeline import PostRecallPipeline
from retrieval.steps import GroupParentsStep, RRFFusionStep, TopKParentsStep

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def actor():
    user = get_user_model().objects.create_user('maintainer')
    user.user_permissions.set(Permission.objects.filter(
        content_type__app_label='catalog', codename__in=['maintain_source', 'read_internal']))
    return user


def ingest(payload, actor, embedder, store=None):
    serializer = SourceImportSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    source, document = import_dtos(serializer.validated_data)
    return import_processed(source, document, actor, embedder=embedder, store=store or DjangoDocumentStore())


def query(text, actor, embedder, **fields):
    s = QuerySerializer(data={'query': text, **fields})
    s.is_valid(raise_exception=True)
    return search(s.validated_data, actor, collector=components.recall_collector(embedder),
        pipeline=components.post_recall_pipeline(), reader=DjangoContextReader(),
        embedding_space=embedder.space_id)


def test_import_dedupe_and_update_keep_ids_without_job_or_publication(actor, embedder, document_payload):
    first = ingest(document_payload, actor, embedder)
    again = ingest(document_payload, actor, embedder)
    assert again.reused and again.context_ids == first.context_ids
    child_id = EvidenceUnit.objects.get(key='battery').pk
    parent = document_payload['document']['contexts'][0]
    parent['body'] = '续航约 9 小时。'
    parent['children'] = [{'key': 'battery', 'body': parent['body'], 'knowledge_type': 'product_spec'}]
    updated = ingest(document_payload, actor, embedder)
    assert not updated.reused and updated.context_ids == first.context_ids
    assert EvidenceUnit.objects.get().pk == child_id
    assert KnowledgeSource.objects.count() == ContextUnit.objects.count() == 1
    result = query('续航', actor, embedder)
    assert result['contexts'][0]['text'] == parent['body']
    assert result['contexts'][0]['matches'][0]['ranks'] == {'keyword': 1, 'vector': 1}


def test_vector_recalls_synonym_and_returns_full_parent_with_hit_locations(actor, embedder, document_payload, settings):
    settings.RETRIEVAL_MIN_COSINE = .5
    document_payload['document']['warnings'] = ['来源警告']
    draft = document_payload['document']['contexts'][0]
    draft['warnings'] = ['父段警告']
    draft['children'][0]['metadata'] = {'detail': '大体积子块元数据' * 1000}
    draft['children'][0]['warnings'] = ['子块附加提示']
    ingest(document_payload, actor, embedder)
    scope = SearchScope(('public',), embedder.space_id)
    assert KeywordRetriever().search('电池能用多久', scope) == []
    result = query('电池能用多久', actor, embedder, top_k=1)
    parent = result['contexts'][0]
    assert result['mode'] == 'hybrid' and parent['text'] == document_payload['document']['contexts'][0]['body']
    assert 'citations' not in parent
    assert len(parent['matches']) == 1
    battery_match = next(match for match in parent['matches'] if match['key'] == 'battery')
    assert battery_match['locator'] == {'paragraph': 1}
    assert parent['warnings'] == ['来源警告', '父段警告']
    assert set(battery_match) == {
        'evidence_id', 'key', 'locator', 'score', 'score_kind', 'route_scores', 'ranks',
    }
    assert parent['matches'][0]['evidence_id'] == str(EvidenceUnit.objects.get(key='battery').pk)
    assert parent['matches'][0]['ranks'] == {'vector': 1}


def test_both_routes_apply_visibility_source_and_type_filters(actor, embedder, document_payload):
    public = ingest(document_payload, actor, embedder)
    private = deepcopy(document_payload)
    private['source'].update(canonical_locator='private:review', visibility='internal')
    internal = ingest(private, actor, embedder)
    reader = get_user_model().objects.create_user('reader')
    assert {c['source']['id'] for c in query('续航', reader, embedder)['contexts']} == {str(public.source_id)}
    assert len(query('续航', actor, embedder)['contexts']) == 2
    assert query('续航', reader, embedder, filters={'source_ids': [str(internal.source_id)]})['contexts'] == []
    assert query('续航', actor, embedder, filters={'knowledge_types': ['repair_case']})['contexts'] == []
    embedder.space_id = 'other-model'
    assert query('续航', actor, embedder)['contexts'] == []


def test_embedding_failure_precedes_storage_and_save_failure_rolls_back(actor, embedder, document_payload):
    with patch.object(embedder, 'embed_documents', side_effect=DomainError('EMBEDDING_UNAVAILABLE', '模型不可用', 502)):
        with pytest.raises(DomainError):
            ingest(document_payload, actor, embedder)
    assert not KnowledgeSource.objects.exists()
    with patch.object(EvidenceUnit.objects, 'update_or_create', side_effect=RuntimeError('write failure')):
        with pytest.raises(RuntimeError):
            ingest(document_payload, actor, embedder)
    assert not KnowledgeSource.objects.exists() and not ContextUnit.objects.exists()


def test_permissions_block_import_before_model_call(actor, embedder, document_payload):
    reader = get_user_model().objects.create_user('reader')
    with patch.object(embedder, 'embed_documents') as encode:
        with pytest.raises(DomainError):
            ingest(document_payload, reader, embedder)
    encode.assert_not_called()


def test_real_token_api_import_search_errors_and_removed_routes(actor, embedder, document_payload):
    from rest_framework.authtoken.models import Token
    client = APIClient()
    assert client.post('/api/v1/search/', {'query': '续航'}, format='json').status_code == 401
    token = Token.objects.create(user=actor)
    client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
    with patch('config.components.embedding_provider', return_value=embedder):
        response = client.post('/api/v1/sources/', document_payload, format='json')
        assert response.status_code == 200, response.data
        result = client.post('/api/v1/search/', {'query': '电池'}, format='json')
        assert result.status_code == 200 and len(result.data['contexts']) == 1
        assert client.post('/api/v1/search/', {'query': '电池', 'extra': 1}, format='json').status_code == 400
        with patch.object(embedder, 'embed_query', side_effect=DomainError('EMBEDDING_UNAVAILABLE', '模型不可用', 502)):
            failure = client.post('/api/v1/search/', {'query': '电池'}, format='json')
            assert failure.status_code == 502 and failure.data['error']['code'] == 'EMBEDDING_UNAVAILABLE'
    for path in ['/health/live/', '/health/ready/', '/api/schema/', '/api/v1/import-jobs/00000000-0000-0000-0000-000000000001/review/']:
        assert client.get(path).status_code == 404


def test_storage_adapter_can_be_replaced(actor, embedder, document_payload):
    from unittest.mock import Mock
    store = Mock()
    ingest(document_payload, actor, embedder, store)
    source, document, vectors, space, supplied_actor = store.save.call_args.args
    assert source.canonical_locator == 'example:laptop-a'
    assert document.contexts[0].key == 'laptop-a' and len(vectors) == 2
    assert space == embedder.space_id and supplied_actor == actor


def test_legacy_data_blocks_destructive_migration(actor, embedder, document_payload):
    import importlib
    from django.apps import apps
    from django.db import connection
    migration = importlib.import_module('catalog.migrations.0003_minimal_rag')
    ingest(document_payload, actor, embedder)
    with connection.schema_editor(atomic=False) as editor:
        with pytest.raises(RuntimeError, match='旧版知识库仍有资料'):
            migration.require_empty_legacy_catalog(apps, editor)
    assert EvidenceUnit.objects.count() == 2


def test_keyword_ranks_before_limit_and_treats_wildcards_as_text(actor, embedder, document_payload):
    ingest(document_payload, actor, embedder)
    higher = deepcopy(document_payload)
    higher['source']['canonical_locator'] = 'example:high'
    parent = higher['document']['contexts'][0]
    parent.update(title='续航', body='续航 model_1 100%charge')
    parent['children'] = [{'key': 'detail', 'body': parent['body']}]
    result = ingest(higher, actor, embedder)
    scope = SearchScope(('public',), embedder.space_id)
    best = KeywordRetriever().search('续航', scope, 1)
    assert best[0].context_id == result.context_ids[0]
    assert len(KeywordRetriever().search('model_1', scope)) == 1
    assert len(KeywordRetriever().search('model%', scope)) == 0


def test_bm25_chinese_query_updates_and_filters_corpus_before_scoring(actor, embedder, document_payload):
    public = ingest(document_payload, actor, embedder)
    scope = SearchScope(('public',), embedder.space_id)
    retriever = KeywordRetriever()
    initial = retriever.search('这台笔记本续航怎么样', scope)
    assert initial[0].context_id == public.context_ids[0]
    assert initial[0].ranks == {'keyword': 1}
    # 不可见、不同模型空间和被类型过滤的资料不影响 BM25 的语料统计。
    for locator, visibility, space, knowledge_type in [
        ('internal', 'internal', embedder.space_id, 'product_spec'),
        ('other-space', 'public', 'other-space', 'product_spec'),
        ('other-type', 'public', embedder.space_id, 'repair_case'),
    ]:
        payload = deepcopy(document_payload)
        payload['source'].update(canonical_locator=locator, visibility=visibility)
        for child in payload['document']['contexts'][0]['children']:
            child['knowledge_type'] = knowledge_type
        added = ingest(payload, actor, embedder)
        KnowledgeSource.objects.filter(pk=added.source_id).update(embedding_space=space)
    filtered = SearchScope(('public',), embedder.space_id, knowledge_types=('product_spec',))
    assert retriever.search('这台笔记本续航怎么样', filtered) == initial
    assert retriever.search('这台笔记本续航怎么样', SearchScope(('public',), embedder.space_id,
                                                              source_ids=(public.source_id,))) == initial
    parent = document_payload['document']['contexts'][0]
    parent.update(title='维修资料', body='风扇噪音。')
    parent['children'] = [{'key': 'fan', 'body': parent['body']}]
    ingest(document_payload, actor, embedder)
    public_scope = SearchScope(('public',), embedder.space_id, source_ids=(public.source_id,))
    assert retriever.search('续航', public_scope) == []
    assert len(retriever.search('风扇噪音', public_scope)) == 1
    KnowledgeSource.objects.filter(pk=public.source_id).delete()
    assert retriever.search('风扇噪音', public_scope) == []


def test_independent_route_thresholds_return_keyword_only_or_no_result(
        actor, embedder, document_payload, settings):
    ingest(document_payload, actor, embedder)
    settings.RETRIEVAL_MIN_COSINE = .5
    with patch.object(embedder, 'embed_query', return_value=[-1, 0]):
        result = query('续航', actor, embedder)
        assert result['result_status'] == 'found'
        parent = result['contexts'][0]
        assert parent['score_kind'] == 'rrf'
        match = parent['matches'][0]
        assert match['ranks'] == {'keyword': 1}
        assert match['score_kind'] == 'rrf'
        assert match['route_scores']['keyword'] > 0 and 'vector' not in match['route_scores']
        settings.RETRIEVAL_MIN_BM25 = 1000
        assert query('续航', actor, embedder)['result_status'] == 'no_result'


def test_multiple_hits_count_top_k_by_parent_and_keep_complete_context(actor, embedder, document_payload):
    document = document_payload['document']
    second = deepcopy(document['contexts'][0])
    second.update(key='laptop-b', title='笔记本 B')
    document['contexts'].append(second)
    imported = ingest(document_payload, actor, embedder)
    result = query('续航', actor, embedder, top_k=2)
    assert {row['context_id'] for row in result['contexts']} == set(map(str, imported.context_ids))
    assert len(query('续航', actor, embedder, top_k=1)['contexts']) == 1
    assert all(row['text'] == second['body'] and 'citations' not in row
               for row in result['contexts'])


def test_api_uses_injected_post_recall_steps_and_exposes_original_route_scores(
        actor, embedder, document_payload):
    from rest_framework.authtoken.models import Token
    from contracts.types import EvidenceBatch

    class RemoveAll:
        input_stage = output_stage = 'evidence'

        def process(self, request, batch):
            return EvidenceBatch([])

    ingest(document_payload, actor, embedder)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Token ' + Token.objects.create(user=actor).key)
    with patch('config.components.embedding_provider', return_value=embedder):
        response = client.post('/api/v1/search/', {'query': '续航'}, format='json')
        assert response.status_code == 200
        match = response.data['contexts'][0]['matches'][0]
        assert match['route_scores']['vector'] == 1
        assert match['route_scores']['keyword'] > 0 and match['score_kind'] == 'rrf'
        custom = PostRecallPipeline([RRFFusionStep(), RemoveAll(), GroupParentsStep(), TopKParentsStep()])
        with patch('config.components.post_recall_pipeline', return_value=custom):
            response = client.post('/api/v1/search/', {'query': '续航'}, format='json')
        assert response.status_code == 200
        assert response.data == {'mode': 'hybrid', 'result_status': 'no_result', 'contexts': []}
