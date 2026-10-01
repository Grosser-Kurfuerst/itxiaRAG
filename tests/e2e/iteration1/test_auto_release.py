import json
from uuid import uuid4

import pytest

from tests.e2e.iteration1.client import account, command, request
from tests.samples import source_input

pytestmark = pytest.mark.e2e


def test_api_and_command_auto_publish_while_manual_requirement_waits(tmp_path):
    name = "s5-" + uuid4().hex
    token = account(name, "maintain_source,review_import,read_internal", tmp_path)
    data = source_input(canonical_locator="manual:" + name)
    code, result = request("POST", "/api/v1/sources/", token, data)
    assert code == 200 and result["is_current"] and result["review_method"] == "auto"
    found = request("POST", "/api/v1/search/", token, {"query": "备份", "filters": {"source_ids": [result["source_id"]]}})[1]
    assert found["result_status"] == "found" and found["flags"] == ["date_unknown"]
    file, metadata = tmp_path / "input.txt", tmp_path / "metadata.json"
    file.write_text(data.pop("input_text"))
    metadata.write_text(json.dumps(data))
    repeated = json.loads(command("kb_import", "--file", file, "--metadata", metadata, "--actor", name))
    assert repeated["build_id"] == result["build_id"] and repeated["reused"]
    data["canonical_locator"] += "-command"
    metadata.write_text(json.dumps(data))
    new = json.loads(command("kb_import", "--file", file, "--metadata", metadata, "--actor", name))
    assert new["is_current"] and new["review_method"] == "auto" and not new["reused"]
    command("kb_job", "--id", new["build_id"], "--actor", name, "--resume")
    code, manual = request("POST", "/api/v1/sources/", token, source_input(canonical_locator="manual:" + name + "-manual", require_manual_review=True))
    assert code == 200 and manual["review_status"] == "pending" and not manual["is_current"]
    command("kb_job", "--id", manual["build_id"], "--actor", name, "--resume", expected=4)
