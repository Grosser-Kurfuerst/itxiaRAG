"""来源与任务事务；不反向依赖导入编排。"""
from django.db import transaction
from django.utils import timezone

from catalog import audit
from catalog.hashes import content_digest
from catalog.models import ImportJob, KnowledgeSource
from catalog.policies import require_permission, visible_scopes
from catalog.profiles import active_profiles
from contracts.errors import DomainError
from catalog.builds import validate_build
from config.runtime import require_available

SOURCE_FIELDS = ("source_type", "canonical_locator", "source_url", "visibility",
                 "authorization_status", "authorization_note")
CONTENT_FIELDS = ("input_text", "format", "title", "author", "source_date",
                  "source_metadata", "domain_metadata", "document_schema", "schema_version")


def check_source_access(source, actor):
    if source.visibility not in visible_scopes(actor):
        raise DomainError("NOT_FOUND", "对象不存在", 404)


def check_import_allowed(source):
    if source.status == "withdrawn":
        raise DomainError("SOURCE_NOT_PUBLISHABLE", "撤回来源不能继续导入", 409)
    if source.authorization_status != "confirmed":
        raise DomainError("AUTHORIZATION_REQUIRED", "导入前须确认当前来源授权")


@transaction.atomic
def submit_import(validated_input, actor, source_id=None):
    """T1 固定输入并去重；只返回任务与 reused，不解析正文。"""
    require_permission(actor, "maintain_source")
    data = validated_input
    profile = active_profiles()
    if source_id is None:
        fields = {key: data[key] for key in SOURCE_FIELDS}
        if fields["authorization_status"] != "confirmed":
            raise DomainError("AUTHORIZATION_REQUIRED", "导入前须确认授权")
        if fields["visibility"] not in visible_scopes(actor):
            raise DomainError("NOT_FOUND", "对象不存在", 404)
        # 唯一约束收敛并发创建；得到来源后统一按相同次序锁行。
        source, created = KnowledgeSource.objects.get_or_create(
            source_type=fields["source_type"], canonical_locator=fields["canonical_locator"],
            defaults={**fields, "created_by": actor},
        )
        source = KnowledgeSource.objects.select_for_update().get(pk=source.pk)
        check_source_access(source, actor)
        if any(getattr(source, key) != value for key, value in fields.items()):
            raise DomainError("SOURCE_METADATA_CONFLICT", "请先显式维护已有来源字段", 409)
        if created:
            audit.record(actor, source, "source_created", visibility=source.visibility)
    else:
        try:
            source = KnowledgeSource.objects.select_for_update().get(pk=source_id)
        except KnowledgeSource.DoesNotExist:
            raise DomainError("NOT_FOUND", "对象不存在", 404) from None
        check_source_access(source, actor)
    check_import_allowed(source)
    content_hash = content_digest(data)
    matches = source.jobs.filter(content_hash=content_hash,
                                 index_profile_hash=profile.index_profile_hash)
    if matches.filter(review_status="rejected").exists():
        raise DomainError("REVIEW_REJECTED", "相同输入已被人工拒绝，请修订后提交", 409)
    current = matches.filter(pk=source.current_build_id, status="succeeded",
                             review_status="approved").first()
    if current:
        return current, True
    candidate = matches.filter(base_build_id=source.current_build_id,
                               status__in=["pending", "succeeded", "failed"]).order_by("-created_at", "id").first()
    if candidate:
        if data["require_manual_review"] and not candidate.quality_report["requested_manual_review"]:
            raise DomainError("REVIEW_REQUIREMENT_CONFLICT", "请查看已有任务的复核要求", 409)
        return candidate, True
    job = ImportJob.objects.create(
        source=source, base_build_id=source.current_build_id, content_hash=content_hash,
        **{key: data[key] for key in CONTENT_FIELDS}, created_by=actor,
        index_profile=profile.index_profile, index_profile_hash=profile.index_profile_hash,
        quality_report={"requested_manual_review": data["require_manual_review"],
                        "redaction_confirmed_by": actor.pk, "review_method": None,
                        "checks": {}, "blocking_errors": [], "review_reasons": [],
                        "warnings": [], "release_policy_hash": None, "review_note": None},
    )
    audit.record(actor, job, "import_submitted", source_id=source.pk, status=job.status)
    return job, False


def _locked_source(source_id, actor, permission="maintain_source"):
    require_permission(actor, permission)
    try:
        return KnowledgeSource.objects.select_for_update().get(
            pk=source_id, visibility__in=visible_scopes(actor))
    except KnowledgeSource.DoesNotExist:
        raise DomainError("NOT_FOUND", "对象不存在", 404) from None


def _locked_job(job_id, actor, permission):
    require_permission(actor, permission)
    source_id = ImportJob.objects.filter(pk=job_id).values_list("source_id", flat=True).first()
    if source_id is None:
        raise DomainError("NOT_FOUND", "对象不存在", 404)
    source = _locked_source(source_id, actor, permission)
    job = ImportJob.objects.select_for_update().get(pk=job_id, source=source)
    job.source = source
    return source, job


@transaction.atomic
def review_job(job_id, decision, note, actor):
    _, job = _locked_job(job_id, actor, "review_import")
    if decision not in ("approved", "rejected") or not isinstance(note, str) or not 1 <= len(note.strip()) <= 2000:
        raise DomainError("INVALID_ARGUMENT", "复核结论和说明非法")
    if job.status != "succeeded" or job.review_status != "pending":
        raise DomainError("INVALID_JOB_STATE", "只可复核构建成功且待审的候选", 409)
    validate_build(job)
    job.review_status, job.reviewed_by, job.reviewed_at = decision, actor, timezone.now()
    job.quality_report.update(review_method="manual", review_note=note.strip(), review_reasons=[])
    job.save(update_fields=["review_status", "reviewed_by", "reviewed_at", "quality_report"])
    audit.record(actor, job, "import_reviewed", decision=decision, method="manual")
    return job


@transaction.atomic
def _publish_transaction(job_id, actor):
    source, job = _locked_job(job_id, actor, "maintain_source")
    if source.status != "active" or source.authorization_status != "confirmed":
        raise DomainError("SOURCE_NOT_PUBLISHABLE", "来源当前不允许发布", 409)
    if job.status != "succeeded" or job.review_status != "approved":
        raise DomainError("INVALID_JOB_STATE", "候选尚未完成构建和放行", 409)
    config = active_profiles()
    if job.index_profile_hash != config.index_profile_hash:
        raise DomainError("PROFILE_CONFLICT", "候选与活动索引配置不兼容", 409)
    validate_build(job)
    if source.current_build_id == job.pk:
        if "publish_error" in job.quality_report:
            job.quality_report.pop("publish_error")
            job.save(update_fields=["quality_report"])
        return job
    if job.base_build_id != source.current_build_id:
        raise DomainError("BUILD_CONFLICT", "候选基于过时的当前构建", 409)
    if job.quality_report.get("review_method") != "manual":
        raise DomainError("INVALID_JOB_STATE", "该放行方式尚未获发布资格", 409)
    previous_id = source.current_build_id
    source.current_build = job
    source.save(update_fields=["current_build", "updated_at"])
    job.quality_report.pop("publish_error", None)
    job.save(update_fields=["quality_report"])
    audit.record(actor, source, "build_published", previous_build_id=previous_id, build_id=job.pk)
    return job


def publish_build(job_id, actor):
    require_available()
    try:
        return _publish_transaction(job_id, actor)
    except DomainError as exc:
        if exc.status == 409:
            with transaction.atomic():
                _, job = _locked_job(job_id, actor, "maintain_source")
                job.quality_report["publish_error"] = {"code": exc.code, "message": exc.message}
                job.save(update_fields=["quality_report"])
        raise


@transaction.atomic
def update_source(source_id, changes, actor):
    source = _locked_source(source_id, actor)
    if source.status == "withdrawn":
        raise DomainError("SOURCE_NOT_PUBLISHABLE", "撤回来源不能通过 PATCH 恢复", 409)
    if source.visibility == "internal" and changes.get("visibility") == "public":
        raise DomainError("INVALID_ARGUMENT", "内部资料不能直接扩大为公开范围", fields={"visibility": ["请另建已脱敏、获公开授权的来源"]})
    if changes.get("visibility", source.visibility) not in visible_scopes(actor):
        raise DomainError("PERMISSION_DENIED", "修改后的内部来源超出账号范围", 403)
    if changes.get("status") == "active" and changes.get("authorization_status", source.authorization_status) != "confirmed":
        raise DomainError("SOURCE_NOT_PUBLISHABLE", "授权未确认不能恢复 active", 409)
    changed = {key: value for key, value in changes.items() if getattr(source, key) != value}
    if changed:
        for key, value in changed.items():
            setattr(source, key, value)
        source.save(update_fields=[*changed, "updated_at"])
        audit.record(actor, source, "source_updated", fields=list(changed),
                     status=source.status, visibility=source.visibility,
                     authorization_status=source.authorization_status)
    return source


@transaction.atomic
def withdraw_source(source_id, actor):
    source = _locked_source(source_id, actor)
    if source.status != "withdrawn":
        source.status = "withdrawn"
        source.save(update_fields=["status", "updated_at"])
        audit.record(actor, source, "source_withdrawn", build_id=source.current_build_id)
    return source
