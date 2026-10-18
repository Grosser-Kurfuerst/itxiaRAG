from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture
def llm_eval(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "eval"))
    import llm_eval
    return llm_eval


def test_schema_digest_changes_with_generated_schema(llm_eval):
    tools = [{"type": "function", "function": {
        "name": "search_knowledge", "description": "检索",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "问题"}}}}}]
    changed = deepcopy(tools)
    changed[0]["function"]["parameters"]["properties"]["query"]["description"] = "改动后的说明"

    assert llm_eval.schema_digest(tools) != llm_eval.schema_digest(changed)
