import uuid

from django.conf import settings
from django.db import models


class SourceType(models.TextChoices):
    MANUAL = "manual"
    YUQUE = "yuque"
    WECHAT = "wechat"


class Visibility(models.TextChoices):
    PUBLIC = "public"
    INTERNAL = "internal"


class Authorization(models.TextChoices):
    CONFIRMED = "confirmed"
    PENDING = "pending"
    REVOKED = "revoked"


class SourceStatus(models.TextChoices):
    ACTIVE = "active"
    DISABLED = "disabled"
    WITHDRAWN = "withdrawn"


class JobStatus(models.TextChoices):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReviewStatus(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TextFormat(models.TextChoices):
    TXT = "txt"
    MARKDOWN = "markdown"


class KnowledgeType(models.TextChoices):
    CONCEPT = "concept"
    PRODUCT_SPEC = "product_spec"
    PURCHASE_RECOMMENDATION = "purchase_recommendation"
    REPAIR_CASE = "repair_case"
    PROCEDURE = "procedure"
    FAQ = "faq"


class EvidenceRole(models.TextChoices):
    SOURCE_STATEMENT = "source_statement"
    MEASURED_FACT = "measured_fact"
    AUTHOR_OPINION = "author_opinion"
    REPAIR_OBSERVATION = "repair_observation"
    CONFIRMED_RESULT = "confirmed_result"
    HYPOTHESIS = "hypothesis"
    MIXED = "mixed"


class ContextRole(models.TextChoices):
    MAIN = "main"
    PREREQUISITE = "prerequisite"
    WARNING = "warning"
    RESULT_BRANCH = "result_branch"
    SUPPORT = "support"


def enum_check(name, field, choices):
    return models.CheckConstraint(condition=models.Q(**{f"{field}__in": choices.values}), name=name)


class KnowledgeSource(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_type = models.CharField(max_length=16, choices=SourceType)
    canonical_locator = models.CharField(max_length=200)
    source_url = models.URLField(max_length=2048, null=True, blank=True)
    visibility = models.CharField(max_length=8, choices=Visibility)
    authorization_status = models.CharField(max_length=12, choices=Authorization)
    authorization_note = models.TextField()
    status = models.CharField(max_length=12, choices=SourceStatus, default=SourceStatus.ACTIVE)
    current_build = models.ForeignKey("ImportJob", null=True, blank=True, on_delete=models.PROTECT, related_name="current_for_sources")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_source"
        permissions = [
            ("read_internal", "读取内部资料"), ("maintain_source", "维护来源"),
            ("review_import", "复核导入"), ("manage_runtime", "管理运行配置"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source_type", "canonical_locator"], name="source_locator_unique"),
            enum_check("source_type_valid", "source_type", SourceType),
            enum_check("source_visibility_valid", "visibility", Visibility),
            enum_check("source_auth_valid", "authorization_status", Authorization),
            enum_check("source_status_valid", "status", SourceStatus),
        ]


class ImportJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(KnowledgeSource, on_delete=models.PROTECT, related_name="jobs")
    base_build_id = models.UUIDField(null=True)
    content_hash = models.CharField(max_length=64)
    input_text = models.TextField()
    format = models.CharField(max_length=16, choices=TextFormat)
    title = models.CharField(max_length=200)
    author = models.CharField(max_length=200, null=True, blank=True)
    source_date = models.DateField(null=True, blank=True)
    source_metadata = models.JSONField(default=dict)
    domain_metadata = models.JSONField(default=dict)
    document_schema = models.CharField(max_length=64)
    schema_version = models.PositiveIntegerField()
    index_profile = models.JSONField(default=dict)
    index_profile_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=JobStatus, default=JobStatus.PENDING)
    review_status = models.CharField(max_length=12, choices=ReviewStatus, default=ReviewStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="reviewed_imports")
    reviewed_at = models.DateTimeField(null=True)
    quality_report = models.JSONField(default=dict)
    attempt_count = models.PositiveIntegerField(default=0)
    current_step = models.CharField(max_length=32, default="submitted")
    error_code = models.CharField(max_length=64, null=True)
    error_detail = models.TextField(null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_imports")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "import_job"
        indexes = [
            models.Index(fields=["source", "content_hash", "index_profile_hash"], name="job_dedupe_idx"),
            models.Index(fields=["status", "created_at"], name="job_status_idx"),
        ]
        constraints = [
            enum_check("job_status_valid", "status", JobStatus),
            enum_check("job_review_valid", "review_status", ReviewStatus),
            enum_check("job_format_valid", "format", TextFormat),
            models.CheckConstraint(condition=models.Q(schema_version__gte=1), name="job_schema_positive"),
        ]


class ContextUnit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    build = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="contexts")
    ordinal = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    body = models.TextField()
    scope_fields = models.JSONField(default=dict)
    locator = models.JSONField(default=dict)
    field_sources = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    knowledge_types = models.JSONField(default=list)

    class Meta:
        db_table = "context_unit"
        ordering = ["ordinal"]
        constraints = [
            models.UniqueConstraint(fields=["build", "ordinal"], name="context_ordinal_unique"),
            models.CheckConstraint(condition=models.Q(ordinal__gte=1), name="context_ordinal_positive"),
        ]


class EvidenceUnit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    context = models.ForeignKey(ContextUnit, on_delete=models.CASCADE, related_name="children")
    ordinal = models.PositiveIntegerField()
    knowledge_type = models.CharField(max_length=32, choices=KnowledgeType)
    evidence_role = models.CharField(max_length=32, choices=EvidenceRole)
    context_role = models.CharField(max_length=32, choices=ContextRole)
    body = models.TextField()
    retrieval_text = models.TextField()
    locator = models.JSONField(default=dict)
    structured_fields = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)

    class Meta:
        db_table = "evidence_unit"
        ordering = ["ordinal"]
        constraints = [
            models.UniqueConstraint(fields=["context", "ordinal"], name="evidence_ordinal_unique"),
            models.CheckConstraint(condition=models.Q(ordinal__gte=1), name="evidence_ordinal_positive"),
            enum_check("evidence_type_valid", "knowledge_type", KnowledgeType),
            enum_check("evidence_role_valid", "evidence_role", EvidenceRole),
            enum_check("evidence_context_role_valid", "context_role", ContextRole),
        ]


class RetrievalSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    index_profile = models.JSONField(default=dict)
    index_profile_hash = models.CharField(max_length=64)
    query_profile = models.JSONField(default=dict)
    query_profile_hash = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "retrieval_settings"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="settings_singleton")]
