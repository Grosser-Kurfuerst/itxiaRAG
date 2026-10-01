from io import StringIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.db import OperationalError
from rest_framework.test import APIClient

from catalog.accounts import configure_account
from catalog.models import ContextUnit, EvidenceUnit, ImportJob, KnowledgeSource
from catalog.services import submit_import
from contracts.serializers import SourceImportSerializer
from contracts.errors import DomainError
from ingestion.pipeline import import_text, resume_import
from tests.samples import source_input

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def actor():
    call_command("kb_init", stdout=StringIO())
    return configure_account("maintainer", ["maintain_source", "read_internal", "review_import"])


def validated(**changes):
    serializer = SourceImportSerializer(data=source_input(**changes))
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def test_api_creates_one_parent_and_child_and_reuses_ids(actor):
    client = APIClient()
    client.force_authenticate(actor)
    data = source_input(input_text="  备份前  \r\n\r\n确认恢复\t", format="markdown")
    first = client.post("/api/v1/sources/", data, format="json")
    assert first.status_code == 200, first.data
    assert first.data["status"] == "succeeded" and first.data["review_status"] == "pending"
    assert first.data["is_current"] is False and first.data["reused"] is False
    job_id = first.data["import_job_id"]
    job = ImportJob.objects.get(pk=job_id)
    assert job.domain_metadata == {} and job.source.current_build_id is None
    parent = ContextUnit.objects.get(build=job)
    child = EvidenceUnit.objects.get(context=parent)
    assert parent.body == child.body == job.input_text == "  备份前  \n\n确认恢复\t"
    assert child.retrieval_text == parent.title + "\n" + child.body
    second = client.post("/api/v1/sources/", data, format="json")
    assert second.status_code == 200 and second.data["reused"] is True
    assert second.data["import_job_id"] == job_id
    assert ContextUnit.objects.get(build=job).pk == parent.pk
    report = client.get(f"/api/v1/import-jobs/{job_id}/")
    assert report.status_code == 200 and len(report.data["contexts"]) == 1
    assert len(report.data["contexts"][0]["children"]) == 1
    assert report.data["input"]["input_text"] == job.input_text
    assert "redaction_confirmed" not in report.data["input"]
    changed = client.post(f"/api/v1/sources/{job.source_id}/imports/", {
        key: value for key, value in {**data, "source_date": "2026-01-01"}.items()
        if key not in {"source_type", "canonical_locator", "source_url", "visibility", "authorization_status", "authorization_note"}
    }, format="json")
    assert changed.status_code == 200 and changed.data["import_job_id"] != job_id


@pytest.mark.parametrize("changes,code", [
    ({"domain_metadata": {"conflicts": []}}, "INVALID_ARGUMENT"),
    ({"source_type": "wechat"}, "INVALID_ARGUMENT"),
    ({"authorization_status": "pending"}, "AUTHORIZATION_REQUIRED"),
    ({"redaction_confirmed": False}, "REDACTION_REVIEW_REQUIRED"),
])
def test_invalid_input_is_not_stored(actor, changes, code):
    client = APIClient()
    client.force_authenticate(actor)
    result = client.post("/api/v1/sources/", source_input(**changes), format="json")
    assert result.status_code == 400 and result.data["error"]["code"] == code
    assert not KnowledgeSource.objects.exists() and not ImportJob.objects.exists()


def test_failed_build_rolls_back_all_products_and_requires_explicit_retry(actor):
    client = APIClient()
    client.force_authenticate(actor)
    with patch("config.components.document_builder", return_value=lambda *_: None):
        result = client.post("/api/v1/sources/", source_input(), format="json")
    assert result.status_code == 200 and result.data["status"] == "failed"
    job = ImportJob.objects.get()
    assert not job.contexts.exists() and job.attempt_count == 1
    with pytest.raises(DomainError) as error:
        resume_import(job.pk, actor)
    assert error.value.code == "INVALID_JOB_STATE"
    # 重复 POST 返回旧失败，不自动 retry。
    repeated = client.post("/api/v1/sources/", source_input(), format="json")
    assert repeated.data["reused"] and repeated.data["status"] == "failed"
    job.refresh_from_db()
    assert job.attempt_count == 1
    rebuilt = resume_import(job.pk, actor, retry=True)
    assert rebuilt.status == "succeeded" and rebuilt.attempt_count == 2
    assert rebuilt.contexts.count() == 1 and rebuilt.contexts.first().children.count() == 1
    with pytest.raises(DomainError) as error:
        resume_import(job.pk, actor, retry=True)
    assert error.value.code == "INVALID_JOB_STATE"


def test_partial_insert_rollback_and_process_interruption_can_resume(actor):
    job, _ = submit_import(validated(), actor)
    class Interrupted(BaseException):
        pass
    with patch("ingestion.pipeline.EvidenceUnit.objects.create", side_effect=Interrupted), pytest.raises(Interrupted):
        resume_import(job.pk, actor)
    job.refresh_from_db()
    assert job.status == "pending" and job.attempt_count == 0
    assert not ContextUnit.objects.exists()
    built = resume_import(job.pk, actor)
    parent_id = built.contexts.get().pk
    assert resume_import(job.pk, actor).contexts.get().pk == parent_id


def test_action_permissions_and_internal_preview_are_separate(actor):
    job, _ = import_text(validated(visibility="internal"), actor)
    public_maintainer = configure_account("public-maintainer", ["maintain_source"])
    plain = configure_account("plain", [])
    reviewer = configure_account("internal-reviewer", ["read_internal", "review_import"])
    client = APIClient()
    for user, expected in [(actor, 200), (public_maintainer, 404), (plain, 403), (reviewer, 200)]:
        client.force_authenticate(user)
        assert client.get(f"/api/v1/import-jobs/{job.pk}/").status_code == expected
    client.force_authenticate(public_maintainer)
    assert client.get(f"/api/v1/import-jobs/{uuid4()}/").status_code == 404
    result = client.post("/api/v1/sources/", source_input(), format="json")
    assert result.status_code == 404  # 不泄露稳定键对应的内部来源。


def test_metadata_and_review_requirement_conflicts_do_not_mutate(actor):
    job, _ = import_text(validated(), actor)
    for changed, code in [({"authorization_note": "不同授权"}, "SOURCE_METADATA_CONFLICT"),
                          ({"require_manual_review": True}, "REVIEW_REQUIREMENT_CONFLICT")]:
        with pytest.raises(DomainError) as error:
            import_text(validated(**changed), actor)
        assert error.value.code == code
    job.refresh_from_db()
    assert not job.quality_report["requested_manual_review"] and ImportJob.objects.count() == 1


def test_audit_and_database_failure_are_not_successful_empty_imports(actor):
    client = APIClient()
    client.force_authenticate(actor)
    with patch("catalog.audit.record", side_effect=OperationalError("private connection")):
        response = client.post("/api/v1/sources/", source_input(), format="json")
    assert response.status_code == 503 and response.data["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "private connection" not in str(response.data)
    assert not KnowledgeSource.objects.exists() and not ImportJob.objects.exists()


def test_maintenance_and_request_size_limit_do_not_store_body(actor, settings):
    client = APIClient()
    client.force_authenticate(actor)
    settings.KB_MAINTENANCE = True
    assert client.post("/api/v1/sources/", source_input(), format="json").status_code == 503
    settings.KB_MAINTENANCE = False
    response = client.post("/api/v1/sources/", source_input(input_text="x" * 131073), format="json")
    assert response.status_code == 413 and not ImportJob.objects.exists()
