"""同步导入编排：T1 提交与 T2 构建分开提交，当前阶段不发布。"""
from dataclasses import asdict
import logging

from django.conf import settings
from django.db import DatabaseError, transaction
from django.utils import timezone

from catalog import audit
from catalog.hashes import content_digest, digest
from catalog.models import ContextUnit, EvidenceUnit, ImportJob
from catalog.profiles import validate_index
from catalog.selectors import maintenance_job
from catalog.services import check_import_allowed, check_source_access, submit_import
from config import components
from contracts.errors import DomainError
from contracts.types import ImportInput
from contracts.text import normalize_text
from ingestion.validation import validate_document

logger = logging.getLogger(__name__)


def require_available():
    if settings.KB_MAINTENANCE:
        raise DomainError("MAINTENANCE", "服务处于维护窗口", 503, retryable=True)


def input_from_job(job):
    return ImportInput(source_id=job.source_id, build_id=job.id, input_text=job.input_text,
                       title=job.title, format=job.format, source_type=job.source.source_type,
                       document_schema=job.document_schema, schema_version=job.schema_version,
                       content_hash=job.content_hash, source_date=job.source_date,
                       domain_metadata=job.domain_metadata)


def check_fixed_input(job):
    try:
        validate_index(job.index_profile)
        if digest(job.index_profile) != job.index_profile_hash:
            raise ValueError("profile_hash")
    except (DomainError, ValueError, TypeError):
        raise DomainError("IMPORT_CONFIGURATION_ERROR", "固定构建配置不受支持或已损坏") from None
    data = {key: getattr(job, key) for key in (
        "input_text", "title", "author", "source_date", "document_schema",
        "schema_version", "source_metadata", "domain_metadata")}
    if (content_digest(data) != job.content_hash or job.domain_metadata != {}
            or job.source_metadata != {} or not job.input_text
            or len(job.input_text) > 8000 or len(job.input_text.split("\n")) > 200
            or normalize_text(job.input_text) != job.input_text):
        raise DomainError("CONTENT_SCHEMA_INVALID", "固定输入校验失败")


def run_import_job(job_id, actor, retry=False, builder=None):
    require_available()
    maintenance_job(job_id, actor, ("maintain_source",))
    builder = builder or components.document_builder()
    attempt = None
    started_at = None
    try:
        with transaction.atomic():
            # 仅锁任务；不取得来源锁，避免与发布的 source→job 次序相反。
            job = (ImportJob.objects.select_for_update(of=("self",))
                   .select_related("source").get(pk=job_id))
            check_source_access(job.source, actor)
            check_import_allowed(job.source)
            if job.review_status == "rejected":
                raise DomainError("REVIEW_REJECTED", "拒绝任务不能恢复或重试", 409)
            if retry and job.status != "failed":
                raise DomainError("INVALID_JOB_STATE", "只有 failed 任务可显式重试", 409)
            if not retry and job.status == "succeeded":
                return job
            if job.status not in (["failed"] if retry else ["pending"]):
                raise DomainError("INVALID_JOB_STATE", "任务当前状态不能构建", 409)
            attempt = job.attempt_count + 1
            started_at = timezone.now()
            job.status, job.attempt_count = "running", attempt
            job.current_step, job.started_at = "processing", started_at
            job.error_code = job.error_detail = None
            job.save()
            if retry:
                audit.record(actor, job, "import_retry", attempt=attempt)
            check_fixed_input(job)
            input = input_from_job(job)
            processed = validate_document(builder(input, job.index_profile), input)
            job.contexts.all().delete()
            for parent in processed.contexts:
                fields = asdict(parent)
                fields.pop("children")
                context = ContextUnit.objects.create(build=job, **fields)
                for child in parent.children:
                    EvidenceUnit.objects.create(context=context, **asdict(child),
                                                retrieval_text=f"{parent.title}\n{child.body}")
            reasons = ["配置未列入自动放行清单"]
            if job.quality_report["requested_manual_review"]:
                reasons.append("调用方要求人工复核")
            job.quality_report.update(
                checks={"schema": "passed", "parent_child": "passed", "locator": "passed"},
                blocking_errors=[], warnings=processed.warnings, review_reasons=reasons,
                processor_id="generic-note", processor_version="1.0.0",
            )
            job.status, job.current_step, job.finished_at = "succeeded", "built", timezone.now()
            job.save()
            return job
    except DatabaseError:
        raise
    except Exception as exc:
        if attempt is None:
            raise  # 权限、授权和动作状态错误不是构建失败。
        expected = isinstance(exc, DomainError) and exc.code in {
            "CONTENT_SCHEMA_INVALID", "IMPORT_CONFIGURATION_ERROR"}
        code = exc.code if expected else "INTERNAL_ERROR"
        detail = exc.message if expected else "导入处理发生内部错误"
        with transaction.atomic():
            job = ImportJob.objects.select_for_update().get(pk=job_id)
            if job.status != "succeeded" and job.attempt_count < attempt:
                job.status, job.attempt_count = "failed", attempt
                job.started_at, job.finished_at = started_at, timezone.now()
                job.current_step = "processing"
                job.error_code, job.error_detail = code, detail
                job.quality_report["blocking_errors"] = [code]
                job.save()
                if retry:
                    audit.record(actor, job, "import_retry_failed", attempt=attempt)
        logger.warning("import_failed", extra={"event": "import_failed", "job_id": job_id,
                                              "error_code": code, "error_class": type(exc).__name__})
        if not expected:
            raise
        return job


def import_text(validated_input, actor, source_id=None, builder=None):
    require_available()
    job, reused = submit_import(validated_input, actor, source_id)
    if job.status == "pending":
        job = run_import_job(job.pk, actor, builder=builder)
    return job, reused


def resume_import(job_id, actor, retry=False):
    require_available()
    job = maintenance_job(job_id, actor, ("maintain_source",))
    if job.review_status == "rejected":
        raise DomainError("REVIEW_REJECTED", "拒绝任务不能恢复或重试", 409)
    if job.status == "succeeded" and not retry:
        return job
    return run_import_job(job_id, actor, retry=retry)
