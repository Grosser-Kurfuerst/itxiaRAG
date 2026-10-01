from dataclasses import replace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from contracts.serializers import SourceImportSerializer, import_dtos, validate_document
from contracts.types import RawDocument
from ingestion.registry import PreprocessorRegistry
from contracts.errors import DomainError


def document(data):
    serializer = SourceImportSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return import_dtos(serializer.validated_data)[1]


def test_dto_roundtrip_preserves_text_and_extensible_metadata(document_payload):
    raw = document_payload['document']['contexts'][0]
    raw['body'] = "第一行  \n第二行"
    raw['children'] = [{"key": "a", "body": raw['body'], "knowledge_type": "new_type"}]
    result = validate_document(document(document_payload))
    assert result.contexts[0].body == "第一行  \n第二行"
    assert result.contexts[0].children[0].knowledge_type == "new_type"
    assert result.metadata['note'].startswith('合成样本')


@pytest.mark.parametrize('fault', ['unknown', 'duplicate_parent', 'duplicate_child', 'unrelated_child', 'empty'])
def test_invalid_structure_is_rejected(document_payload, fault):
    d = document_payload['document']
    if fault == 'unknown': d['parser_path'] = 'some.module'
    if fault == 'duplicate_parent': d['contexts'] *= 2
    if fault == 'duplicate_child': d['contexts'][0]['children'] *= 2
    if fault == 'unrelated_child': d['contexts'][0]['children'][0]['body'] = '不属于父段'
    if fault == 'empty': d['contexts'] = []
    with pytest.raises(ValidationError):
        document(document_payload)


def test_registry_validates_plugin_output_and_requires_explicit_registration(document_payload):
    expected = document(document_payload)
    plugin = Mock(process=Mock(return_value=expected))
    registry = PreprocessorRegistry()
    raw = RawDocument(b'raw', 'text/plain')
    with pytest.raises(DomainError, match='尚未接入'):
        registry.process(raw, 'product_review', 1)
    registry.register('product_review', 1, plugin)
    assert registry.process(raw, 'product_review', 1) == expected
    plugin.process.assert_called_once_with(raw)
    with pytest.raises(ValueError):
        registry.register('product_review', 1, plugin)
    plugin.process.return_value = replace(expected, document_schema='repair_case')
    with pytest.raises(DomainError, match='不符'):
        registry.process(raw, 'product_review', 1)
