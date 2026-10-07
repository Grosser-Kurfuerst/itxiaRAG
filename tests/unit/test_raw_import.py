from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from config import components
from contracts.errors import DomainError
from contracts.serializers import RawSourceImportSerializer, import_raw_dtos
from contracts.types import RawDocument, SourceSpec
from ingestion.pipeline import import_raw


def payload(document="正文"):
    return {
        "source": {"source_type": "yuque", "canonical_locator": "doc:1", "visibility": "public"},
        "preprocess": {"schema": "experience_case", "version": 1},
        "raw": {"content": document, "media_type": "text/markdown", "metadata": {"title": "经验"}},
    }


def test_raw_serializer_converts_text_without_losing_newlines():
    serializer = RawSourceImportSerializer(data=payload("第一行\n\n第二行"))
    serializer.is_valid(raise_exception=True)
    source, raw, schema, version = import_raw_dtos(serializer.validated_data)
    assert source.source_type == "yuque"
    assert raw.content == "第一行\n\n第二行".encode()
    assert raw.metadata["title"] == "经验"
    assert (schema, version) == ("experience_case", 1)


@pytest.mark.parametrize("field", ["source", "preprocess", "raw"])
def test_raw_serializer_rejects_unknown_nested_fields(field):
    data = payload()
    data[field]["unknown"] = 1
    with pytest.raises(ValidationError):
        RawSourceImportSerializer(data=data).is_valid(raise_exception=True)


@pytest.mark.parametrize("metadata", [
    {"title": "经验", "source_date": "not-a-date"},
    {"title": "经验", "entity_headings": ["A", "A"]},
    {"title": "经验", "entity_headings": "A"},
    {"title": "经验", "warnings": "not-a-list"},
])
def test_raw_metadata_rejects_malformed_known_fields(metadata):
    data = payload()
    data["raw"]["metadata"] = metadata
    with pytest.raises(ValidationError):
        RawSourceImportSerializer(data=data).is_valid(raise_exception=True)


def test_preprocessor_code_path_cannot_be_selected_by_request():
    data = payload()
    data["preprocess"]["processor_path"] = "some.module"
    with pytest.raises(ValidationError, match="未知字段"):
        RawSourceImportSerializer(data=data).is_valid(raise_exception=True)


def test_raw_metadata_is_open_for_future_source_specific_fields():
    data = payload()
    data["raw"]["metadata"].update({"yuque_space_id": "space-1", "custom_flag": True})
    serializer = RawSourceImportSerializer(data=data)
    assert serializer.is_valid(), serializer.errors


def actor(*permissions):
    return Mock(is_authenticated=True, is_active=True,
                has_perm=Mock(side_effect=lambda name: name.split(".")[-1] in permissions))


def test_import_raw_uses_registered_pipeline_and_standard_embedding_save_contract():
    data = payload("# 经验\n\n## 黑屏案例\n\n续航约 9 小时。")
    serializer = RawSourceImportSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    source, raw, schema, version = import_raw_dtos(serializer.validated_data)
    embedder = Mock(space_id="test-space")
    embedder.embed_documents.side_effect = lambda texts: [[1.0, 0.0] for _ in texts]
    store = Mock()
    user = actor("maintain_source")
    import_raw(source, raw, schema, version, user,
               registry=components.preprocessors(), embedder=embedder, store=store)
    saved_source, document, vectors, space, saved_actor = store.save.call_args.args
    assert saved_source == source and saved_actor is user and space == "test-space"
    assert document.document_schema == schema and document.title == "经验"
    expected_texts = [f"{p.title}\n{c.body}" for p in document.contexts for c in p.children]
    assert embedder.embed_documents.call_args.args[0] == expected_texts
    assert len(vectors) == len(expected_texts)


def test_permissions_and_source_visibility_block_preprocessing_and_model_calls():
    registry, embedder, store = Mock(), Mock(), Mock()
    source = SourceSpec("yuque", "doc:1", "internal")
    for user, code in [(actor(), "PERMISSION_DENIED"), (actor("maintain_source"), "NOT_FOUND")]:
        with pytest.raises(DomainError) as error:
            import_raw(source, RawDocument(b"raw", "text/plain"), "experience_case", 1, user,
                       registry=registry, embedder=embedder, store=store)
        assert error.value.code == code
    registry.process.assert_not_called()
    embedder.embed_documents.assert_not_called()
    store.save.assert_not_called()


def test_preprocessing_failure_does_not_call_model_or_store():
    embedder, store = Mock(), Mock()
    with pytest.raises(DomainError) as error:
        import_raw(SourceSpec("yuque", "doc:1", "public"), RawDocument(b"raw", "application/pdf"),
                   "experience_case", 1, actor("maintain_source"),
                   registry=components.preprocessors(), embedder=embedder, store=store)
    assert error.value.code == "UNSUPPORTED_MEDIA_TYPE"
    embedder.embed_documents.assert_not_called()
    store.save.assert_not_called()
