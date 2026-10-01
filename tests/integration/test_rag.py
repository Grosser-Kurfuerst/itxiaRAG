from copy import deepcopy
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from catalog.models import ContextUnit, EvidenceUnit, KnowledgeSource
from catalog.selectors import DjangoContextReader
from catalog.storage import DjangoDocumentStore
from contracts.errors import DomainError
from contracts.query import QuerySerializer
from contracts.serializers import SourceImportSerializer, import_dtos
from contracts.types import SearchScope
from ingestion.pipeline import import_processed
from retrieval.hybrid import HybridRetriever, RRFRanker
from retrieval.keyword import KeywordRetriever
from retrieval.service import search
from retrieval.vector import VectorRetriever

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
    return search(s.validated_data, actor, retriever=HybridRetriever(
        [KeywordRetriever(), VectorRetriever(embedder)], RRFRanker()), reader=DjangoContextReader(),
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


def test_vector_recalls_synonym_and_returns_full_parent_with_citations(actor, embedder, document_payload):
    ingest(document_payload, actor, embedder)
    scope = SearchScope(('public',), embedder.space_id)
    assert KeywordRetriever().search('电池能用多久', scope) == []
    result = query('电池能用多久', actor, embedder, top_k=1)
    parent = result['contexts'][0]
    assert result['mode'] == 'hybrid' and parent['text'] == document_payload['document']['contexts'][0]['body']
    assert len(parent['citations']) == 2
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
