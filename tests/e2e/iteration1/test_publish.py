from uuid import uuid4

import pytest

from tests.e2e.iteration1.client import account, command, request
from tests.samples import source_input

pytestmark = pytest.mark.e2e


def test_manual_publish_update_reference_and_withdraw_through_real_entries(tmp_path):
    name = "s3-" + uuid4().hex
    token = account(name, "maintain_source,review_import,read_internal", tmp_path)
    reader = account(name + "-reader", "", tmp_path)
    data = source_input(canonical_locator="manual:" + name, require_manual_review=True)
    code, first = request("POST", "/api/v1/sources/", token, data)
    assert code == 200 and first["review_status"] == "pending"
    job_id = first["build_id"]
    report = request("GET", f"/api/v1/import-jobs/{job_id}/", token)[1]
    parent = report["contexts"][0]
    context_path = f"/api/v1/contexts/{parent['context_id']}/"
    assert request("GET", context_path, reader)[0] == 404
    command("kb_job", "--id", job_id, "--actor", name, "--review", "approved", "--note", "核对完整合成原文")
    assert request("GET", context_path, reader)[0] == 404
    command("kb_publish", "--id", job_id, "--actor", name)
    code, visible = request("GET", context_path, reader)
    assert code == 200 and visible["text"] == report["input"]["input_text"]
    assert "matched_evidence_ids" not in visible
    child_id = parent["children"][0]["evidence_id"]
    child_path = f"/api/v1/evidence/{child_id}/"
    assert request("GET", child_path, reader)[1]["context"]["context_id"] == parent["context_id"]
    # 同一已发布版本可幂等发布；更新正文后旧引用失效。
    assert request("POST", f"/api/v1/import-jobs/{job_id}/publish/", token, {})[1]["is_current"]
    content = {key: value for key, value in data.items() if key not in {
        "source_type", "canonical_locator", "source_url", "visibility", "authorization_status", "authorization_note"}}
    code, new = request("POST", f"/api/v1/sources/{first['source_id']}/imports/", token,
                        {**content, "input_text": "更新后的备份建议。"})
    assert code == 200
    assert request("POST", f"/api/v1/import-jobs/{new['build_id']}/review/", token,
                   {"decision": "approved", "note": "核对更新"})[0] == 200
    assert request("POST", f"/api/v1/import-jobs/{new['build_id']}/publish/", token, {})[0] == 200
    assert request("GET", context_path, reader)[0] == 404
    assert request("GET", child_path, reader)[0] == 404
    new_parent = request("GET", f"/api/v1/import-jobs/{new['build_id']}/", token)[1]["contexts"][0]
    new_path = f"/api/v1/contexts/{new_parent['context_id']}/"
    assert request("GET", new_path, reader)[1]["text"] == "更新后的备份建议。"
    source_path = f"/api/v1/sources/{first['source_id']}/"
    assert request("PATCH", source_path, token, {"visibility": "internal"})[0] == 200
    assert request("GET", new_path, reader)[0] == 404
    assert request("GET", new_path, token)[0] == 200
    command("kb_withdraw", "--source", first["source_id"], "--actor", name)
    assert request("GET", new_path, token)[0] == 404
    assert request("PATCH", source_path, token, {"status": "active"})[0] == 409
    assert request("POST", source_path + "withdraw/", token, {})[0] == 200
