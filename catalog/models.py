import uuid

from django.db import models


class KnowledgeSource(models.Model):
    """当前文档；原始文件抓取和历史版本不属于当前存储职责。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_type = models.CharField(max_length=64)
    canonical_locator = models.CharField(max_length=200)
    source_url = models.URLField(max_length=2048, null=True, blank=True)
    title = models.CharField(max_length=200)
    source_date = models.DateField(null=True, blank=True)
    visibility = models.CharField(max_length=8, choices=[("public", "公开"), ("internal", "内部")])
    document_schema = models.CharField(max_length=64)
    schema_version = models.PositiveIntegerField(default=1)
    metadata = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    content_hash = models.CharField(max_length=64)
    embedding_space = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_source"
        permissions = [("read_internal", "读取内部资料"), ("maintain_source", "维护来源")]
        constraints = [
            models.UniqueConstraint(fields=["source_type", "canonical_locator"], name="source_locator_unique"),
            models.CheckConstraint(condition=models.Q(visibility__in=["public", "internal"]), name="source_visibility_valid"),
        ]


class ContextUnit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(KnowledgeSource, on_delete=models.CASCADE, related_name="contexts")
    key = models.CharField(max_length=100)
    ordinal = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    body = models.TextField()
    locator = models.JSONField(default=dict)
    metadata = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)

    class Meta:
        db_table = "context_unit"
        ordering = ["ordinal"]
        constraints = [models.UniqueConstraint(fields=["source", "key"], name="context_key_unique")]


class EvidenceUnit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    context = models.ForeignKey(ContextUnit, on_delete=models.CASCADE, related_name="children")
    key = models.CharField(max_length=100)
    ordinal = models.PositiveIntegerField()
    body = models.TextField()
    retrieval_text = models.TextField()
    knowledge_type = models.CharField(max_length=64, default="concept")
    locator = models.JSONField(default=dict)
    metadata = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    embedding = models.JSONField()

    class Meta:
        db_table = "evidence_unit"
        ordering = ["ordinal"]
        constraints = [models.UniqueConstraint(fields=["context", "key"], name="evidence_key_unique")]
