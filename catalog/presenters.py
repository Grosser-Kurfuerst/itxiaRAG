from catalog.services import CONTENT_FIELDS


def job_summary(job, reused=False):
    return {
        "source_id": job.source_id, "import_job_id": job.pk, "build_id": job.pk,
        "status": job.status, "review_status": job.review_status,
        "review_method": job.quality_report.get("review_method"),
        "is_current": job.source.current_build_id == job.pk, "reused": reused,
        "error_code": job.error_code or job.quality_report.get("publish_error", {}).get("code"),
    }


def job_report(job):
    contexts = []
    for parent in job.contexts.all():
        item = {key: getattr(parent, key) for key in (
            "ordinal", "title", "body", "scope_fields", "field_sources", "locator", "knowledge_types", "warnings")}
        item["context_id"] = parent.pk
        item["children"] = [{"evidence_id": child.pk, **{key: getattr(child, key) for key in (
            "ordinal", "body", "retrieval_text", "knowledge_type", "evidence_role",
            "context_role", "locator", "structured_fields", "warnings")}}
            for child in parent.children.all()]
        contexts.append(item)
    return {**job_summary(job), "input": {key: getattr(job, key) for key in CONTENT_FIELDS},
            "contexts": contexts, **{key: getattr(job, key) for key in (
                "quality_report", "current_step", "attempt_count", "created_at",
                "started_at", "finished_at", "error_detail")}}
