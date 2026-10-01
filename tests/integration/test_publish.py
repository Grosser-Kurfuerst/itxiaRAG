from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.admin.models import LogEntry
from django.db import OperationalError
from rest_framework.test import APIClient

from catalog.accounts import configure_account
from catalog.models import ImportJob, KnowledgeSource
from catalog.services import publish_build, review_job, update_source, withdraw_source
from contracts.errors import DomainError
from ingestion.pipeline import import_text, resume_import
from tests.integration.test_import import actor, validated

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def approve(job, actor):
    return review_job(job.pk, "approved", "已核对合成原文和定位", actor)


def paths(job):
    parent = job.contexts.get()
    return f"/api/v1/contexts/{parent.pk}/", f"/api/v1/evidence/{parent.children.get().pk}/"


def test_candidate_requires_review_and_publish_then_reader_can_reference(actor):
    job, _ = import_text(validated(), actor)
    client = APIClient()
    reader = configure_account("reader", [])
    client.force_authenticate(reader)
    context_path, evidence_path = paths(job)
    assert client.get(context_path).status_code == 404
    approve(job, actor)
    assert client.get(context_path).status_code == 404
    published = publish_build(job.pk, actor)
    assert published.source.current_build_id == job.pk
    response = client.get(context_path)
    assert response.status_code == 200
    assert response.data["text"] == job.input_text and response.data["match_status"] == "uncertain"
    assert response.data["flags"] == ["date_unknown"] and "matched_evidence_ids" not in response.data
    assert client.get(evidence_path).data["context"]["context_id"] == response.data["context_id"]
    count = LogEntry.objects.count()
    assert publish_build(job.pk, actor).pk == job.pk
    assert LogEntry.objects.count() == count


def test_new_build_switch_invalidates_old_ids_and_stale_candidate_is_conflict(actor):
    old, _ = import_text(validated(), actor)
    approve(old, actor)
    publish_build(old.pk, actor)
    first, _ = import_text(validated(input_text="新稿 A 备份"), actor)
    second, _ = import_text(validated(input_text="新稿 B 备份"), actor)
    approve(first, actor)
    approve(second, actor)
    client = APIClient()
    client.force_authenticate(actor)
    assert client.get(paths(old)[0]).status_code == 200
    assert client.get(paths(first)[0]).status_code == 404
    publish_build(first.pk, actor)
    for path in paths(old):
        assert client.get(path).status_code == 404
    assert client.get(paths(first)[0]).status_code == 200
    with pytest.raises(DomainError) as error:
        publish_build(second.pk, actor)
    assert error.value.code == "BUILD_CONFLICT"
    source = KnowledgeSource.objects.get(pk=old.source_id)
    assert source.current_build_id == first.pk
    second.refresh_from_db()
    assert second.status == "succeeded" and second.quality_report["publish_error"]["code"] == "BUILD_CONFLICT"


def test_rejected_and_failed_jobs_cannot_be_published_or_bypassed(actor):
    job, _ = import_text(validated(), actor)
    review_job(job.pk, "rejected", "合成样本不应上线", actor)
    for action in [lambda: publish_build(job.pk, actor), lambda: resume_import(job.pk, actor),
                   lambda: resume_import(job.pk, actor, retry=True), lambda: import_text(validated(), actor)]:
        with pytest.raises(DomainError):
            action()
    assert KnowledgeSource.objects.get(pk=job.source_id).current_build_id is None
    failed, _ = import_text(validated(input_text="失败的另一个输入"), actor, builder=lambda *_: None)
    with pytest.raises(DomainError) as error:
        approve(failed, actor)
    assert error.value.code == "INVALID_JOB_STATE"


@pytest.mark.parametrize("changes", [{"status": "disabled"}, {"authorization_status": "revoked"}, {"visibility": "internal"}])
def test_source_restrictions_immediately_hide_details(actor, changes):
    job, _ = import_text(validated(), actor)
    approve(job, actor)
    publish_build(job.pk, actor)
    client = APIClient()
    client.force_authenticate(configure_account("reader", []))
    assert client.get(paths(job)[0]).status_code == 200
    update_source(job.source_id, changes, actor)
    for path in paths(job):
        assert client.get(path).status_code == 404
    if changes == {"visibility": "internal"}:
        client.force_authenticate(actor)
        assert client.get(paths(job)[0]).status_code == 200
        with pytest.raises(DomainError):
            update_source(job.source_id, {"visibility": "public"}, actor)
    elif changes == {"status": "disabled"}:
        update_source(job.source_id, {"status": "active"}, actor)
        assert client.get(paths(job)[0]).status_code == 200


def test_withdrawal_is_terminal_idempotent_and_works_in_maintenance(actor, settings):
    job, _ = import_text(validated(), actor)
    approve(job, actor)
    publish_build(job.pk, actor)
    settings.KB_MAINTENANCE = True
    source = withdraw_source(job.source_id, actor)
    assert source.current_build_id == job.pk and source.status == "withdrawn"
    count = LogEntry.objects.count()
    withdraw_source(job.source_id, actor)
    assert LogEntry.objects.count() == count
    with pytest.raises(DomainError) as error:
        publish_build(job.pk, actor)
    assert error.value.code == "MAINTENANCE"
    settings.KB_MAINTENANCE = False
    with pytest.raises(DomainError) as error:
        publish_build(job.pk, actor)
    assert error.value.code == "SOURCE_NOT_PUBLISHABLE"
    with pytest.raises(DomainError):
        update_source(job.source_id, {"status": "active"}, actor)


def test_publish_audit_failure_rolls_back_pointer_and_preserves_old_data(actor):
    old, _ = import_text(validated(), actor)
    approve(old, actor)
    publish_build(old.pk, actor)
    new, _ = import_text(validated(input_text="新稿"), actor)
    approve(new, actor)
    with patch("catalog.audit.record", side_effect=OperationalError("audit unavailable")), pytest.raises(OperationalError):
        publish_build(new.pk, actor)
    assert KnowledgeSource.objects.get(pk=old.source_id).current_build_id == old.pk
    new.refresh_from_db()
    assert new.status == "succeeded" and new.contexts.count() == 1
    assert publish_build(new.pk, actor).source.current_build_id == new.pk


def test_maintenance_actions_check_action_before_object_existence(actor):
    job, _ = import_text(validated(visibility="internal"), actor)
    public_maintainer = configure_account("public", ["maintain_source", "review_import"])
    reader = configure_account("reader", [])
    client = APIClient()
    for user, expected in [(reader, 403), (public_maintainer, 404)]:
        client.force_authenticate(user)
        for id in [job.pk, uuid4()]:
            response = client.post(f"/api/v1/import-jobs/{id}/review/", {"decision": "approved", "note": "合成"}, format="json")
            assert response.status_code == expected


def test_patch_unknown_or_empty_fields_are_rejected(actor):
    job, _ = import_text(validated(), actor)
    client = APIClient()
    client.force_authenticate(actor)
    for changes in [{}, {"status": "withdrawn"}, {"current_build_id": str(job.pk)}, {"visibility": None}]:
        response = client.patch(f"/api/v1/sources/{job.source_id}/", changes, format="json")
        assert response.status_code == 400 and response.data["error"]["code"] == "INVALID_ARGUMENT"
