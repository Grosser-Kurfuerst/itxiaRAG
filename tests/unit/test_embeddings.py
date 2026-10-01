from io import BytesIO
import json
from unittest.mock import patch
from urllib.error import URLError

import pytest

from contracts.errors import DomainError
from embeddings.openai_compatible import OpenAICompatibleEmbedding


def provider(**changes):
    return OpenAICompatibleEmbedding(**{
        'base_url': 'http://localhost/v1', 'model': 'test', 'dimensions': 2, 'revision': 'v1', **changes})


def test_embedding_adapter_batches_and_restores_provider_index_order():
    calls = []
    def respond(request, timeout):
        calls.append(json.loads(request.data))
        return BytesIO(json.dumps({'data': [
            {'index': 1, 'embedding': [0, 1]}, {'index': 0, 'embedding': [1, 0]}]}).encode())
    with patch('embeddings.openai_compatible.urlopen', side_effect=respond):
        assert provider(batch_size=2).embed_documents(['a', 'b', 'c', 'd']) == [[1, 0], [0, 1]] * 2
    assert [c['input'] for c in calls] == [['a', 'b'], ['c', 'd']]
    assert provider().space_id != provider(revision='v2').space_id


def test_model_failure_is_explicit_and_never_becomes_fake_vectors():
    with patch('embeddings.openai_compatible.urlopen', side_effect=URLError('secret')):
        with pytest.raises(DomainError) as error:
            provider().embed_query('问题')
    assert error.value.code == 'EMBEDDING_UNAVAILABLE'
    assert 'secret' not in str(error.value)


def test_missing_model_configuration_is_not_replaced_by_fake_embeddings(settings):
    from config.components import embedding_provider
    settings.EMBEDDING = {'base_url': '', 'model': '', 'dimensions': 0, 'revision': ''}
    with pytest.raises(DomainError) as error:
        embedding_provider()
    assert error.value.code == 'EMBEDDING_NOT_CONFIGURED'
