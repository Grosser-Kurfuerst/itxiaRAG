import json
from unittest.mock import patch

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.db import OperationalError
from rest_framework.test import APIClient

from catalog import release_policy
from catalog.models import ImportJob, KnowledgeSource
from catalog.services import submit_import, try_auto_release, review_job, publish_build
from contracts.errors import DomainError
from ingestion.pipeline import import_text, resume_import, run_import_job
from tests.integration.test_import import actor, validated
from tests.integration.test_search import query
from retrieval.service import search
from tests.samples import source_input

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_normal_import_auto_publishes_and_audits_system_identity(actor):
    job, _ = import_text(validated(), actor)
    assert job.status == "succeeded" and job.review_status == "approved"
    assert job.quality_report["review_method"] == "auto" and job.source.current_build_id == job.pk
    assert job.reviewed_by.username == "kb-system"
    assert len(job.quality_report["release_policy_hash"]) == 64
    assert search(query(), actor)["contexts"][0]["text"] == job.input_text
    assert search(query(), actor)["flags"] == ["date_unknown"]
    entries = [entry for entry in LogEntry.objects.all() if json.loads(entry.change_message)["action"] in ("import_reviewed", "build_published")]
    assert len(entries) == 2 and all(entry.user_id == job.reviewed_by_id for entry in entries)
    count = LogEntry.objects.count()
    again, reused = import_text(validated(), actor)
    assert again.pk == job.pk and reused and LogEntry.objects.count() == count


def test_manual_requirement_and_missing_qualification_keep_candidates_and_allow_manual_publish(actor, settings, tmp_path):
    manual, _ = import_text(validated(require_manual_review=True), actor)
    assert manual.review_status == "pending" and manual.source.current_build_id is None
    assert manual.quality_report["review_reasons"] == ["调用方要求人工复核"]
    settings.PROFILE_DIR = tmp_path
    (tmp_path / "auto-release.json").write_text('{"schema_version":1,"entries":[]}')
    unqualified, _ = import_text(validated(input_text="未登记配置的备份资料"), actor)
    assert unqualified.review_status == "pending"
    assert unqualified.quality_report["review_reasons"] == ["配置未列入自动放行清单"]
    review_job(unqualified.pk, "approved", "人工核对合成样本", actor)
    published = resume_import(unqualified.pk, actor)
    assert published.source.current_build_id == unqualified.pk and published.quality_report["review_method"] == "manual"
    assert try_auto_release(unqualified.pk).quality_report["review_method"] == "manual"


@pytest.mark.parametrize("interrupt_after_review", [False, True])
def test_successful_build_resume_reuses_parent_child_and_publishes_once(actor, interrupt_after_review):
    job, _ = submit_import(validated(), actor)
    built = run_import_job(job.pk, actor)
    parent = built.contexts.get()
    child_id = parent.children.get().pk
    if interrupt_after_review:
        try_auto_release(job.pk)
    resumed = resume_import(job.pk, actor)
    assert resumed.source.current_build_id == job.pk and resumed.attempt_count == 1
    assert resumed.contexts.get().pk == parent.pk and parent.children.get().pk == child_id
    count = LogEntry.objects.count()
    resume_import(job.pk, actor)
    assert LogEntry.objects.count() == count


def test_auto_approved_candidate_rechecks_removed_qualification_before_publish(actor, settings, tmp_path):
    job, _ = submit_import(validated(), actor)
    run_import_job(job.pk, actor)
    try_auto_release(job.pk)
    settings.PROFILE_DIR = tmp_path
    (tmp_path / "auto-release.json").write_text('{"schema_version":1,"entries":[]}')
    result = resume_import(job.pk, actor)
    assert result.review_status == "approved" and result.source.current_build_id is None
    assert result.quality_report["publish_error"]["code"] == "AUTO_RELEASE_NOT_QUALIFIED"
    assert result.status == "succeeded" and result.contexts.count() == 1


def test_auto_publish_conflict_preserves_current_build_and_products(actor):
    first, _ = submit_import(validated(), actor)
    second, _ = submit_import(validated(input_text="另一个候选"), actor)
    run_import_job(first.pk, actor)
    run_import_job(second.pk, actor)
    resume_import(first.pk, actor)
    result = resume_import(second.pk, actor)
    assert result.quality_report["publish_error"]["code"] == "BUILD_CONFLICT"
    assert KnowledgeSource.objects.get().current_build_id == first.pk
    assert result.status == "succeeded" and result.contexts.count() == 1


def test_auto_flow_never_overwrites_manual_rejection(actor):
    job, _ = import_text(validated(require_manual_review=True), actor)
    rejected = review_job(job.pk, "rejected", "合成拒绝", actor)
    before = rejected.quality_report.copy()
    assert try_auto_release(job.pk).review_status == "rejected"
    with pytest.raises(DomainError) as error:
        resume_import(job.pk, actor)
    assert error.value.code == "REVIEW_REJECTED"
    rejected.refresh_from_db()
    assert rejected.quality_report == before


@pytest.mark.parametrize("failure", ["policy", "account", "audit"])
def test_t3_dependency_failure_keeps_successful_products_and_can_resume(actor, settings, tmp_path, failure):
    client = APIClient()
    client.force_authenticate(actor)
    directory = settings.PROFILE_DIR
    system = get_user_model().objects.get(username="kb-system")
    if failure == "policy":
        settings.PROFILE_DIR = tmp_path
    elif failure == "account":
        system.is_active = False
        system.save()
    original = __import__('catalog.audit', fromlist=['record']).record
    def failing_audit(actor, obj, action, **changes):
        if action == "import_reviewed":
            raise OperationalError("private detail")
        return original(actor, obj, action, **changes)
    with patch("catalog.audit.record", side_effect=failing_audit if failure == "audit" else original):
        response = client.post("/api/v1/sources/", source_input(), format="json")
    assert response.status_code == 503
    job = ImportJob.objects.get()
    assert job.status == "succeeded" and job.review_status == "pending" and job.source.current_build_id is None
    parent_id = job.contexts.get().pk
    settings.PROFILE_DIR = directory
    system.is_active = True
    system.save()
    result = resume_import(job.pk, actor)
    assert result.source.current_build_id == job.pk and result.contexts.get().pk == parent_id


def test_publish_audit_failure_after_auto_review_keeps_review_for_resume(actor):
    from catalog import audit
    original = audit.record
    def fail(actor, obj, action, **changes):
        if action == "build_published": raise OperationalError("audit unavailable")
        return original(actor, obj, action, **changes)
    with patch("catalog.audit.record", side_effect=fail), pytest.raises(OperationalError):
        import_text(validated(), actor)
    job = ImportJob.objects.get()
    assert job.review_status == "approved" and job.source.current_build_id is None
    assert resume_import(job.pk, actor).source.current_build_id == job.pk
