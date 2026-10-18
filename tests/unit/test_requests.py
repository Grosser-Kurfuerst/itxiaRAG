import pytest
from pydantic import BaseModel, Field, ValidationError
from pydantic_core import PydanticCustomError
from rest_framework.exceptions import ValidationError as DRFValidationError

from contracts.products import Conditions, RecommendInput
from contracts.query import QueryInput
from contracts.requests import parse_model, require_text, strip_text


class Nested(BaseModel):
    items: list[int] = Field(max_length=2)


class Request(BaseModel):
    nested: Nested


def test_parse_model_uses_dotted_paths_and_list_indexes():
    with pytest.raises(DRFValidationError) as error:
        parse_model(RecommendInput, {"conditions": {"brands": ["苹果", "不存在"]}})
    assert set(error.value.detail) == {"conditions.brands.1"}


def test_parse_model_uses_non_field_errors_for_whole_body_and_nested_model():
    with pytest.raises(DRFValidationError) as error:
        parse_model(Request, [])
    assert set(error.value.detail) == {"non_field_errors"}

    with pytest.raises(DRFValidationError) as error:
        parse_model(RecommendInput, {"conditions": {"price_min": 9000, "price_max": 8000}})
    assert list(error.value.detail) == ["conditions"]
    assert "price_min 不能大于 price_max" in str(error.value.detail["conditions"])


def test_strip_text_matches_char_field_rules():
    assert strip_text(" \t续航\n ") == "续航"
    assert strip_text("") == ""
    with pytest.raises(PydanticCustomError, match="空字节"):
        strip_text("续\x00航")


def test_require_text_matches_text_field_rules():
    assert require_text(" \t续航\n ") == "续航"
    with pytest.raises(PydanticCustomError, match="文本不能为空"):
        require_text(" \n ")
    with pytest.raises(PydanticCustomError, match="空字节"):
        require_text("续\x00航")
    with pytest.raises(PydanticCustomError, match="合法 UTF-8"):
        require_text("\ud800")


def test_request_models_reject_unknown_fields_and_drop_nulls():
    with pytest.raises(ValidationError):
        QueryInput.model_validate({"query": "续航", "unknown": 1})
    with pytest.raises(ValidationError):
        Conditions.model_validate({"thin_light": True})

    assert QueryInput.model_validate({"query": "续航", "filters": None, "top_k": None}).model_dump(
        exclude_none=True) == {"query": "续航", "filters": {}, "top_k": 5}
    assert RecommendInput.model_validate({"conditions": None, "top_k": None}).model_dump(
        exclude_none=True) == {"conditions": {}, "preference": "", "top_k": 5}
