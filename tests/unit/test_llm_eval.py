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


def test_main_writes_specialist_report_without_external_services(llm_eval, monkeypatch, tmp_path):
    import json
    import sys
    from types import SimpleNamespace
    spec, extra, out = (tmp_path / n for n in ('spec.json', 'extra.json', 'result.json'))
    spec.write_text(json.dumps({'queries': []}))
    extra.write_text(json.dumps({'version': 'test', 'queries': []}))
    monkeypatch.setattr(sys, 'argv', ['llm_eval.py', str(spec), str(extra), str(out)])
    monkeypatch.setattr(llm_eval, 'load_corpus', lambda *a: object())
    monkeypatch.setattr(llm_eval, 'Recommender', lambda: object())
    monkeypatch.setattr(llm_eval, 'load_tools', lambda: ('prompt', []))
    monkeypatch.setattr(llm_eval, 'ChatModel', lambda *a: SimpleNamespace(model='test-model'))
    for name in ('spec_rows', 'extra_rows', 'chain_rows'):
        monkeypatch.setattr(llm_eval, name, lambda *a: [])
    printed = []
    monkeypatch.setattr(llm_eval, 'print_report', lambda **kwargs: printed.append(kwargs))
    llm_eval.main()
    assert set(printed[0]) == {'meta', 'spec', 'extra', 'chain'}
    assert json.loads(out.read_text())['meta']['metric_version'] == 'strict-v2'
