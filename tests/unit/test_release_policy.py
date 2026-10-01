from copy import deepcopy
from types import SimpleNamespace

import pytest

from catalog.release_policy import qualified, review_reasons, validate_policy

pytestmark = pytest.mark.unit


def policy():
    return {"schema_version": 1, "entries": [{"document_schema": "generic_note", "schema_version": 1,
        "index_profile_hash": "a" * 64, "sample_report": "synthetic-report.md", "confirmed_by": "test reviewer"}]}


def test_qualification_requires_schema_version_and_actual_index_hash():
    job = SimpleNamespace(document_schema="generic_note", schema_version=1, index_profile_hash="a" * 64,
                          quality_report={"requested_manual_review": False, "warnings": ["原始日期未知"]})
    value = validate_policy(policy())
    assert qualified(value, job) and review_reasons(value, job) == []
    job.quality_report["requested_manual_review"] = True
    assert review_reasons(value, job) == ["调用方要求人工复核"]
    job.index_profile_hash = "b" * 64
    assert not qualified(value, job)


@pytest.mark.parametrize("change", ["unknown", "duplicate", "missing_report", "invalid_hash", "bool_version"])
def test_release_policy_rejects_invalid_or_untraceable_entries(change):
    value = policy()
    if change == "unknown": value["skip_checks"] = True
    if change == "duplicate": value["entries"].append(deepcopy(value["entries"][0]))
    if change == "missing_report": value["entries"][0]["sample_report"] = " "
    if change == "invalid_hash": value["entries"][0]["index_profile_hash"] = "example"
    if change == "bool_version": value["schema_version"] = True
    with pytest.raises(ValueError):
        validate_policy(value)
