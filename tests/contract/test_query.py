from dataclasses import replace
from decimal import Decimal

import pytest

from contracts.query import ConfirmedContextSerializer, QuerySerializer
from contracts.errors import DomainError
from retrieval.query_processing import NoOpQueryProcessor, QueryInput, prepare

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("changes,field", [
    ({"query": None}, "query"), ({"query": True}, "query"), ({"query": " "}, "query"),
    ({"query": "a" * 2001}, "query"), ({"top_k": True}, "top_k"), ({"top_k": "5"}, "top_k"),
    ({"top_k": 21}, "top_k"), ({"query_raw": "x"}, "query_raw"),
    ({"confirmed_context": None}, "confirmed_context"),
    ({"filters": {"knowledge_types": []}}, "filters"),
    ({"filters": {"knowledge_types": ["concept", "concept"]}}, "filters"),
    ({"filters": {"source_ids": [1]}}, "filters"),
    ({"filters": {"source_ids": None}}, "filters"),
    ({"confirmed_context": {"checks_done": None}}, "confirmed_context"),
    ({"confirmed_context": {"model_year": True}}, "confirmed_context"),
    ({"confirmed_context": {"budget": {"max": "100"}}}, "confirmed_context"),
    ({"confirmed_context": {"budget": {"max": 1.111}}}, "confirmed_context"),
    ({"confirmed_context": {"budget": {"min": 20, "max": 10}}}, "confirmed_context"),
    ({"confirmed_context": {"budget": {"max": 0}}}, "confirmed_context"),
    ({"confirmed_context": {"use_cases": ["other"]}}, "confirmed_context"),
    ({"confirmed_context": {"unknown": "x"}}, "confirmed_context"),
])
def test_query_invalid_types_fail_before_capability_check(changes, field):
    serializer = QuerySerializer(data={"query": "备份", **changes})
    assert not serializer.is_valid()
    assert field in serializer.errors


@pytest.mark.parametrize("changes", [{"scenario": "purchase"}, {"scenario": "repair"},
    {"confirmed_context": {"checks_done": []}}, {"confirmed_context": {"budget": None}}])
def test_valid_but_unavailable_capabilities_are_explicit(changes):
    with pytest.raises(DomainError) as error:
        QuerySerializer(data={"query": "备份", **changes}).is_valid(raise_exception=True)
    assert error.value.code == "CAPABILITY_NOT_AVAILABLE"


def test_complete_context_contract_keeps_null_and_known_empty_distinct():
    serializer = ConfirmedContextSerializer(data={"checks_done": [], "os_version": None,
        "budget": {"min": 0, "max": 4000.25}, "use_cases": ["other"], "use_case_note": "专业软件"})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["checks_done"] == []
    assert "symptoms" not in serializer.validated_data
    assert serializer.validated_data["budget"]["max"] == Decimal("4000.25")
    assert serializer.validated_data["budget"]["currency"] == "CNY"


class FakeProcessor:
    def __init__(self, kind):
        self.kind = kind

    def prepare_query(self, input):
        baseline = NoOpQueryProcessor().prepare_query(input)
        if self.kind == "error":
            raise RuntimeError("private query")
        if self.kind == "timeout":
            raise TimeoutError
        if self.kind == "invalid":
            return {"retrieval_query": "x"}
        if self.kind == "empty":
            return replace(baseline, status="applied", retrieval_query=" ")
        if self.kind == "scenario":
            return replace(baseline, effective_scenario="repair")
        return replace(baseline, status="applied", retrieval_query="备份")


@pytest.mark.parametrize("kind", ["error", "timeout", "invalid", "empty", "scenario"])
def test_processor_failures_fall_back_without_overwriting_input(kind):
    input = QueryInput("原始问题", "general")
    output = prepare(input, "auto", FakeProcessor(kind), 50)
    assert output.retrieval_query == "原始问题"
    assert output.status == "fallback" and output.scenario_source == "caller"
    assert output.suggested_context == {}


def test_bypass_does_not_call_processor_and_noop_is_normal():
    class Never:
        def prepare_query(self, input):
            pytest.fail("bypass 不应调用")
    assert prepare(QueryInput("备份"), "bypass", Never(), 50).status == "bypassed"
    assert prepare(QueryInput("备份"), "auto", NoOpQueryProcessor(), 50).status == "noop"
    assert prepare(QueryInput("原问题"), "auto", FakeProcessor("rewrite"), 50).retrieval_query == "备份"
    ticks = iter([0, 0.06])
    assert prepare(QueryInput("备份"), "auto", NoOpQueryProcessor(), 50, clock=lambda: next(ticks)).status == "fallback"
