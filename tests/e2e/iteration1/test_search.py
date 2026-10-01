from uuid import UUID, uuid4

import pytest

from tests.e2e.iteration1.client import account, request
from tests.samples import source_input

pytestmark = pytest.mark.e2e


def test_search_public_internal_candidate_and_withdrawal_through_http(tmp_path):
    name = "s4-" + uuid4().hex
    maintainer = account(name, "maintain_source,review_import,read_internal", tmp_path)
    reader = account(name + "-reader", "", tmp_path)
    jobs = []
    for suffix, visibility in [("public", "public"), ("internal", "internal"), ("candidate", "public")]:
        code, job = request("POST", "/api/v1/sources/", maintainer, source_input(
            canonical_locator="manual:" + name + suffix, visibility=visibility, require_manual_review=True))
        assert code == 200
        if suffix != "candidate":
            assert request("POST", f"/api/v1/import-jobs/{job['build_id']}/review/", maintainer,
                           {"decision": "approved", "note": "已核对合成样本"})[0] == 200
            assert request("POST", f"/api/v1/import-jobs/{job['build_id']}/publish/", maintainer, {})[0] == 200
        jobs.append(job)
    query = {"query": "备份", "filters": {"source_ids": [job["source_id"] for job in jobs]}}
    code, result = request("POST", "/api/v1/search/", reader, query)
    assert code == 200 and UUID(result["query_id"])
    assert result["result_status"] == "found" and result["feedback_available"] is False
    assert [c["source_id"] for c in result["contexts"]] == [jobs[0]["source_id"]]
    parent = result["contexts"][0]
    assert request("GET", f"/api/v1/contexts/{parent['context_id']}/", reader)[1]["text"] == parent["text"]
    assert len(request("POST", "/api/v1/search/", maintainer, query)[1]["contexts"]) == 2
    assert request("POST", "/api/v1/search/", reader, {**query, "preprocess": "bypass"})[1]["query_processing"]["status"] == "bypassed"
    request("POST", f"/api/v1/sources/{jobs[0]['source_id']}/withdraw/", maintainer, {})
    assert request("POST", "/api/v1/search/", reader, query)[1]["result_status"] == "no_result"
    assert request("POST", "/api/v1/search/", reader, {"query": "备份", "scenario": "purchase"})[1]["error"]["code"] == "CAPABILITY_NOT_AVAILABLE"
    error = request("POST", "/api/v1/search/", reader, {"query": "备份", "filters": {"source_ids": []}})[1]["error"]
    assert error["code"] == "INVALID_ARGUMENT" and "filters.source_ids" in error["field_errors"]
