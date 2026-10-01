from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from rest_framework.exceptions import ValidationError

from catalog.hashes import content_digest
from catalog.profiles import load_profiles
from contracts.errors import DomainError
from contracts.serializers import SourceImportSerializer
from contracts.text import normalize_text
from contracts.types import ImportInput
from ingestion.registry import parse_and_chunk
from ingestion.validation import validate_document
from tests.samples import source_input

pytestmark = pytest.mark.unit


def validated(**changes):
    value = SourceImportSerializer(data=source_input(**changes))
    value.is_valid(raise_exception=True)
    return value.validated_data


def test_markdown_preserves_line_end_spaces_indent_and_interior_blank_lines():
    original = "\ufeff\r\n  第一行  \r\n\r\n  第二行\t\r\n \t\r\n"
    result = validated(input_text=original, format="markdown")
    assert result["input_text"] == "  第一行  \n\n  第二行\t"
    assert content_digest(result) == content_digest(validated(input_text=result["input_text"], format="txt"))
    assert content_digest(result) != content_digest({**result, "input_text": "  第一行\n\n  第二行\t"})


@pytest.mark.parametrize("field,value", [
    ("domain_metadata", {"knowledge_type": "concept"}), ("domain_metadata", {"conflicts": []}),
    ("domain_metadata", None), ("domain_metadata", []), ("source_metadata", {"channel": "wechat"}),
    ("schema_version", True), ("schema_version", "1"), ("require_manual_review", 0),
    ("redaction_confirmed", "true"), ("author", 1), ("title", False),
    ("extra", 1), ("source_type", "wechat"), ("document_schema", "product_review"),
])
def test_invalid_input_has_stable_field_error(field, value):
    with pytest.raises(ValidationError) as error:
        validated(**{field: value})
    assert field in error.value.detail


@pytest.mark.parametrize("changes,code", [
    ({"redaction_confirmed": False}, "REDACTION_REVIEW_REQUIRED"),
    ({"authorization_status": "pending"}, "AUTHORIZATION_REQUIRED"),
    ({"input_text": "x" * 8001}, "INPUT_TOO_LARGE"),
    ({"input_text": "x\n" * 201}, "INPUT_TOO_LARGE"),
])
def test_unsupported_submission_is_rejected_before_storage(changes, code):
    with pytest.raises(DomainError) as error:
        validated(**changes)
    assert error.value.code == code


def test_empty_metadata_defaults_and_hash_fields_are_consistent():
    omitted = source_input()
    omitted.pop("domain_metadata")
    value = SourceImportSerializer(data=omitted)
    assert value.is_valid(), value.errors
    base = validated()
    assert content_digest(value.validated_data) == content_digest(base)
    assert content_digest({**base, "require_manual_review": True}) == content_digest(base)
    assert content_digest(validated(title="改标题")) != content_digest(base)
    assert content_digest(validated(source_date="2026-01-01")) != content_digest(base)


def test_parser_processor_contract_preserves_full_text_without_database():
    data = validated(input_text="第一行  \n第二行", format="markdown")
    input = ImportInput(uuid4(), uuid4(), data["input_text"], data["title"], data["format"],
                        "manual", "generic_note", 1, content_digest(data), None)
    profile = load_profiles(Path(__file__).resolve().parents[2] / "profiles/iteration1")["index_profile"]
    document = validate_document(parse_and_chunk(input, profile), input)
    parent = document.contexts[0]
    child = parent.children[0]
    assert parent.body == child.body == "第一行  \n第二行"
    assert child.knowledge_type == "concept" and child.structured_fields == {"applicability": "unknown"}
    assert parent.locator["spans"][0]["line_end"] == 2 and parent.warnings == ["原始日期未知"]
    with pytest.raises(DomainError) as error:
        validate_document(replace(document, contexts=[replace(parent, body="截断")]), input)
    assert error.value.code == "CONTENT_SCHEMA_INVALID"
