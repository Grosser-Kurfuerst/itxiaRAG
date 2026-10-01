"""来源与任务事务；不反向依赖导入编排。"""
from django.db import transaction

from catalog import audit
from catalog.hashes import content_digest
from catalog.models import ImportJob, KnowledgeSource
from catalog.policies import require_permission, visible_scopes
from catalog.profiles import active_profiles
from contracts.errors import DomainError

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
