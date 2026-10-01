from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import OperationalError
from rest_framework.test import APIClient

from catalog.accounts import configure_account
from catalog.hashes import digest
from catalog.models import RetrievalSettings
from catalog.services import review_job, publish_build, withdraw_source, update_source
from contracts.query import QuerySerializer, SearchResponseSerializer
from ingestion.pipeline import import_text
from retrieval.service import search
from retrieval.keyword import KeywordBackend, SearchScope
from tests.contract.test_query import FakeProcessor
from tests.integration.test_import import actor, validated

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def query(**changes):
    serializer = QuerySerializer(data={"query": "备份", **changes})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def published(actor, **changes):
    job, _ = import_text(validated(canonical_locator="manual:" + uuid4().hex, require_manual_review=True, **changes), actor)
    review_job(job.pk, "approved", "合成样本核对", actor)
    return publish_build(job.pk, actor)


def test_scope_filters_and_response_contract_use_only_current_visible_sources(actor):
    public = published(actor)
    internal = published(actor, visibility="internal", title="内部备份")
    import_text(validated(canonical_locator="manual:candidate", require_manual_review=True), actor)
    reader = configure_account("reader", [])
    result = search(query(), reader)
    assert [item["source_id"] for item in result["contexts"]] == [str(public.source_id)]
    item = result["contexts"][0]
    assert item["text"] == public.input_text
    assert item["matched_evidence_ids"] == [item["citations"][0]["evidence_id"]]
    assert result["feedback_available"] is False and result["execution"] == {"status": "ok", "mode": "keyword", "warnings": []}
    serializer = SearchResponseSerializer(data=result)
    assert serializer.is_valid(), serializer.errors
    assert result["index_profile_hash"] == public.index_profile_hash
    assert result["flags"] == ["date_unknown"]
    assert len(search(query(), actor)["contexts"]) == 2
    assert search(query(filters={"source_ids": [str(internal.source_id)]}), reader)["result_status"] == "no_result"
    assert search(query(filters={"source_ids": [str(uuid4())]}), reader)["result_status"] == "no_result"
    assert search(query(filters={"knowledge_types": ["procedure"]}), actor)["result_status"] == "no_result"


def test_database_ranks_before_limit_and_breaks_ties_by_evidence_id(actor):
    # 超过 100 份低分文档先入库，最高分最后入库，不能先 LIMIT 后评分。
    lower = [published(actor, title="合成笔记", input_text="备份") for _ in range(101)]
    highest = published(actor, title="备份", input_text="备份")
    backend = KeywordBackend()
    rows = backend.search("备份", SearchScope(actor, highest.index_profile_hash), 100)
    assert len(rows) == 100
    assert rows[0].evidence_id == highest.contexts.get().children.get().pk and rows[0].score == 130
    expected = sorted(job.contexts.get().children.get().pk for job in lower)
    assert [item.evidence_id for item in rows[1:]] == expected[:99]
    assert search(query(top_k=1), actor)["contexts"][0]["source_id"] == str(highest.source_id)
    assert backend.build(highest.pk, highest.index_profile).evidence_count == 1


def test_literals_are_not_sql_wildcards(actor):
    published(actor, input_text="model_1 100%charge")
    published(actor, input_text="modelX1 100Xcharge")
    assert len(search(query(query="model_1"), actor)["contexts"]) == 1
    assert len(search(query(query="100%charge"), actor)["contexts"]) == 1


def test_rewrite_and_fallback_reach_real_backend_without_expanding_scope(actor):
    public = published(actor)
    internal = published(actor, visibility="internal")
    reader = configure_account("reader", [])
    data = query(query="无匹配", filters={"source_ids": [str(public.source_id), str(internal.source_id)]})
    result = search(data, reader, processor=FakeProcessor("rewrite"))
    assert [c["source_id"] for c in result["contexts"]] == [str(public.source_id)]
    result = search(data, reader, processor=FakeProcessor("timeout"))
    assert result["result_status"] == "insufficient_evidence" and result["execution"]["status"] == "degraded"
    assert search(data, reader)["result_status"] == "no_result"
    assert search(query(preprocess="bypass"), reader)["query_processing"]["status"] == "bypassed"


@pytest.mark.parametrize("changes", [{"visibility": "internal"}, {"status": "disabled"}, {"authorization_status": "revoked"}])
def test_restrictions_apply_to_search_and_final_recheck(actor, changes):
    job = published(actor)
    reader = configure_account("reader", [])
    class ChangingBackend(KeywordBackend):
        def search(self, *args):
            result = super().search(*args)
            update_source(job.source_id, changes, actor)
            return result
    result = search(query(), reader, backend=ChangingBackend())
    assert result["contexts"] == [] and result["flags"] == []
    assert result["result_status"] == "insufficient_evidence"
    assert result["execution"]["warnings"] == ["CANDIDATES_INVALIDATED"]
    assert search(query(), reader)["result_status"] == "no_result"


def test_final_check_runs_after_parent_assembly_and_trace_failure_is_nonfatal(actor):
    from retrieval.service import context_response
    job = published(actor)
    def revoke(parent, ids):
        result = context_response(parent, ids)
        withdraw_source(job.source_id, actor)
        return result
    with patch("retrieval.service.context_response", side_effect=revoke):
        result = search(query(), actor)
    assert result["contexts"] == [] and result["result_status"] == "insufficient_evidence"
    with patch("retrieval.service.logger.info", side_effect=OSError):
        assert search(query(), actor)["result_status"] == "no_result"


def test_response_budget_skips_parent_and_does_not_rebuild_index(actor):
    job = published(actor)
    obj = RetrievalSettings.objects.get(pk=1)
    obj.query_profile["response_context_bytes"] = 100
    obj.query_profile_hash = digest(obj.query_profile)
    obj.save()
    result = search(query(), actor)
    assert result["contexts"] == [] and result["flags"] == ["context_incomplete"]
    assert result["result_status"] == "insufficient_evidence"
    assert result["index_profile_hash"] == job.index_profile_hash


def test_ready_and_search_dependency_errors_are_not_empty_results(actor, settings):
    client = APIClient()
    client.force_authenticate(actor)
    assert client.get("/health/ready/").status_code == 200
    settings.KB_MAINTENANCE = True
    assert client.get("/health/ready/").status_code == 503
    assert client.post("/api/v1/search/", {"query": "备份"}, format="json").data["error"]["code"] == "MAINTENANCE"
    settings.KB_MAINTENANCE = False
    with patch("retrieval.keyword.KeywordBackend.search", side_effect=OperationalError("private")):
        assert client.get("/health/ready/").status_code == 503
        assert client.post("/api/v1/search/", {"query": "备份"}, format="json").data["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    RetrievalSettings.objects.filter(pk=1).update(query_profile_hash="f" * 64)
    assert client.get("/health/ready/").status_code == 503
    assert client.post("/api/v1/search/", {"query": "备份"}, format="json").status_code == 503
