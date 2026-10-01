import json
from pathlib import Path
from uuid import uuid4

import pytest

from tests.e2e.iteration1.client import command, request

pytestmark = pytest.mark.e2e


def test_demo_seed_is_repeatable_without_republishing_withdrawn_sources(tmp_path):
    prefix = "demo-" + uuid4().hex[:16]
    args = ("kb_seed_demo", "--prefix", prefix, "--token-dir", tmp_path)
    command(*args, expected=2)
    first = json.loads(command(*args, "--confirm-demo"))
    account_tokens = {a["username"].removeprefix(prefix + "-"): Path(a["token_file"]).read_text().strip()
                      for a in first["accounts"]}
    assert all(Path(a["token_file"]).stat().st_mode & 0o777 == 0o600 for a in first["accounts"])
    public, internal, pending = first["sources"]
    assert public["is_current"] and internal["is_current"] and not pending["is_current"]
    query = {"query": "备份", "filters": {"source_ids": [s["source_id"] for s in first["sources"]]}}
    assert len(request("POST", "/api/v1/search/", account_tokens["reader"], query)[1]["contexts"]) == 1
    assert len(request("POST", "/api/v1/search/", account_tokens["member"], query)[1]["contexts"]) == 2
    # 演示维护者可沿正式人工路径复核、发布候选。
    job_id = pending["build_id"]
    report_path = tmp_path / "pending-report.md"
    command("kb_job", "--id", job_id, "--actor", prefix + "-maintainer", "--report", report_path)
    assert '"children"' in report_path.read_text()
    command("kb_job", "--id", job_id, "--actor", prefix + "-maintainer", "--review", "approved", "--note", "演示核对")
    command("kb_publish", "--id", job_id, "--actor", prefix + "-maintainer")
    command("kb_withdraw", "--source", public["source_id"], "--actor", prefix + "-maintainer")
    second = json.loads(command(*args, "--confirm-demo"))
    assert [s["source_id"] for s in second["sources"]] == [s["source_id"] for s in first["sources"]]
    assert second["sources"][0]["status"] == "withdrawn"
    assert second["sources"][2]["current_build_id"] == job_id
    result = request("POST", "/api/v1/search/", account_tokens["reader"], query)[1]
    assert [c["source_id"] for c in result["contexts"]] == [pending["source_id"]]
