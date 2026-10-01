from catalog.hashes import content_digest, digest
from catalog.profiles import validate_index
from contracts.errors import DomainError
from contracts.types import ImportInput, ContextDraft, EvidenceDraft, ProcessedDocument
from contracts.text import normalize_text
from contracts.document_validation import validate_document


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


def validate_build(job):
    check_fixed_input(job)
    parents = list(job.contexts.prefetch_related("children").all())
    drafts = []
    for parent in parents:
        children = []
        for child in parent.children.all():
            if child.retrieval_text != parent.title + "\n" + child.body:
                raise DomainError("CONTENT_SCHEMA_INVALID", "检索文本与父子原文不一致", 409)
            children.append(EvidenceDraft(**{key: getattr(child, key) for key in (
                "ordinal", "body", "knowledge_type", "evidence_role", "context_role",
                "locator", "structured_fields", "warnings")}))
        drafts.append(ContextDraft(children=children, **{key: getattr(parent, key) for key in (
            "ordinal", "title", "body", "scope_fields", "field_sources", "locator",
            "knowledge_types", "warnings")}))
    try:
        validate_document(ProcessedDocument(drafts, job.quality_report.get("warnings", [])), input_from_job(job))
    except DomainError as exc:
        raise DomainError(exc.code, exc.message, 409) from None
    return parents
