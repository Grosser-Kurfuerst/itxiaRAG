import json
from uuid import uuid4

import pytest

from tests.e2e.iteration1.client import account, command, request
from tests.samples import source_input

pytestmark = pytest.mark.e2e


def test_real_http_and_cli_import_dedup_report_and_visibility(tmp_path):
    name = "s2-" + uuid4().hex
    token = account(name, "maintain_source,review_import,read_internal", tmp_path)
    plain = account(name + "-reader", "", tmp_path)
    data = source_input(canonical_locator="manual:" + name, format="markdown", require_manual_review=True,
                        input_text="\ufeff\r\n  备份第一行  \r\n\r\n第二行\t\r\n")
    code, first = request("POST", "/api/v1/sources/", token, data)
    assert code == 200 and first["status"] == "succeeded" and first["review_status"] == "pending", first
    assert not first["is_current"]
    job_path = f"/api/v1/import-jobs/{first['build_id']}/"
    code, report = request("GET", job_path, token)
    assert code == 200
    parent = report["contexts"][0]
    assert parent["body"] == parent["children"][0]["body"] == "  备份第一行  \n\n第二行\t"
    assert parent["children"][0]["knowledge_type"] == "concept"
    assert parent["locator"]["spans"][0]["line_end"] == 3
    assert report["input"]["domain_metadata"] == {}
    assert request("GET", job_path, plain)[0] == 403
    assert request("POST", "/api/v1/sources/", token, data)[1]["build_id"] == first["build_id"]
    # 命令使用相同 Schema，重复输入复用 HTTP 创建的同一任务。
    source_file = tmp_path / "note.md"
    source_file.write_text(data["input_text"], encoding="utf-8")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({k: v for k, v in data.items() if k != "input_text"}), encoding="utf-8")
    output = command("kb_import", "--file", source_file, "--metadata", metadata,
                     "--actor", name, expected=4)
    assert json.loads(output)["build_id"] == first["build_id"]
    report_file = tmp_path / "report.md"
    command("kb_job", "--id", first["build_id"], "--actor", name, "--report", report_file)
    assert report_file.stat().st_mode & 0o777 == 0o600
    assert parent["context_id"] in report_file.read_text()
    command("kb_job", "--id", first["build_id"], "--actor", name, "--resume", expected=4)
    assert request("GET", job_path, token)[1]["contexts"][0]["context_id"] == parent["context_id"]
    assert request("POST", job_path + "retry/", token, {})[0] == 409
    # 未发布的候选即使存在详情入口也不可见。
    assert request("GET", f"/api/v1/contexts/{parent['context_id']}/", token)[0] == 404
    code, invalid = request("POST", "/api/v1/sources/", token, {**data, "domain_metadata": {"conflicts": []}})
    assert code == 400 and invalid["error"]["code"] == "INVALID_ARGUMENT"
