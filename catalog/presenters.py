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


def source_summary(source):
    return {key: getattr(source, key) for key in (
        "id", "source_type", "canonical_locator", "source_url", "visibility",
        "authorization_status", "authorization_note", "status", "current_build_id", "created_at", "updated_at")}


def context_response(parent, matched_evidence_ids=None):
    job, source = parent.build, parent.build.source
    result = {
        "context_id": parent.pk, "title": parent.title, "text": parent.body,
        "scope_fields": parent.scope_fields, "source_id": source.pk, "source_title": job.title,
        "source_url": source.source_url, "build_id": job.pk, "content_hash": job.content_hash,
        "source_date": job.source_date, "source_type": source.source_type,
        "document_schema": job.document_schema, "schema_version": job.schema_version,
        "knowledge_types": parent.knowledge_types, "locator": parent.locator,
        "field_sources": parent.field_sources, "match_status": "uncertain",
        "warnings": parent.warnings, "flags": ["date_unknown"] if job.source_date is None else [],
        "citations": [{"evidence_id": child.pk, "context_role": child.context_role,
                       "knowledge_type": child.knowledge_type, "evidence_role": child.evidence_role,
                       "locator": child.locator} for child in parent.children.all()],
    }
    if matched_evidence_ids is not None:
        result["matched_evidence_ids"] = matched_evidence_ids
    return result


def evidence_response(child):
    return {"evidence_id": child.pk, "context_id": child.context_id,
            **{key: getattr(child, key) for key in (
                "body", "knowledge_type", "evidence_role", "context_role", "locator", "structured_fields", "warnings")},
            "context": context_response(child.context)}
