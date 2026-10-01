"""API、管理命令共用的严格输入契约；不依赖 ORM。"""
import re

from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from contracts.errors import DomainError
from contracts.text import normalize_text


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if type(data) is not dict:
            raise serializers.ValidationError({"non_field_errors": ["必须是 JSON 对象"]})
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: ["未知字段"] for key in sorted(unknown)})
        return super().to_internal_value(data)


class StrictString(serializers.CharField):
    def run_validation(self, data=serializers.empty):
        if data is not serializers.empty and data is not None:
            if type(data) is not str:
                raise serializers.ValidationError("必须是字符串")
            try:
                data.encode("utf-8")
            except UnicodeError:
                raise serializers.ValidationError("必须是合法 UTF-8 文本") from None
            if "\x00" in data:
                raise serializers.ValidationError("文本不能包含空字节")
        return super().run_validation(data)


class StrictChoice(serializers.ChoiceField):
    def to_internal_value(self, data):
        if type(data) is not str:
            raise serializers.ValidationError("必须是字符串枚举")
        return super().to_internal_value(data.strip())


class StrictInteger(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            raise serializers.ValidationError("必须是整数，不能是布尔值或数字字符串")
        return super().to_internal_value(data)


class StrictBoolean(serializers.BooleanField):
    def to_internal_value(self, data):
        if type(data) is not bool:
            raise serializers.ValidationError("必须是布尔值")
        return data


class ISODate(serializers.DateField):
    def to_internal_value(self, data):
        if type(data) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data.strip()):
            raise serializers.ValidationError("必须是 ISO 日期 YYYY-MM-DD")
        return super().to_internal_value(data.strip())


class EmptyObject(StrictSerializer):
    pass


@extend_schema_field({"type": "object", "additionalProperties": False})
class EmptyObjectField(serializers.DictField):
    def to_internal_value(self, data):
        if type(data) is not dict:
            raise serializers.ValidationError("必须是空 JSON 对象")
        if data:
            raise serializers.ValidationError({key: ["未知字段"] for key in data})
        return {}


class BodyText(StrictString):
    def to_internal_value(self, data):
        value = normalize_text(super().to_internal_value(data))
        if not 1 <= len(value) <= 8000 or len(value.split("\n")) > 200:
            raise DomainError("INPUT_TOO_LARGE", "正文须为 1–8000 字且最多 200 行", fields={"input_text": ["正文长度或行数超限"]})
        return value


class ImportSnapshotSerializer(StrictSerializer):
    title = StrictString(max_length=200, allow_blank=False)
    input_text = BodyText(trim_whitespace=False, allow_blank=False)
    format = StrictChoice(choices=["txt", "markdown"])
    author = StrictString(max_length=200, allow_null=True, default=None)
    source_date = ISODate(allow_null=True, default=None)
    document_schema = StrictChoice(choices=["generic_note"])
    schema_version = StrictInteger(min_value=1, max_value=1)
    source_metadata = EmptyObjectField(default=dict)
    domain_metadata = EmptyObjectField(default=dict)


class ImportContentSerializer(ImportSnapshotSerializer):
    redaction_confirmed = StrictBoolean()
    require_manual_review = StrictBoolean(default=False)

    def validate_redaction_confirmed(self, value):
        if not value:
            raise DomainError("REDACTION_REVIEW_REQUIRED", "请先确认正文适于声明的可见范围", fields={"redaction_confirmed": ["必须确认"]})
        return value


class SourceImportSerializer(ImportContentSerializer):
    source_type = StrictChoice(choices=["manual"])
    canonical_locator = StrictString(max_length=200)
    source_url = StrictString(max_length=2048, allow_null=True, default=None)
    visibility = StrictChoice(choices=["public", "internal"])
    authorization_status = StrictChoice(choices=["confirmed", "pending", "revoked"])
    authorization_note = StrictString(max_length=2000)

    def validate_canonical_locator(self, value):
        if not re.fullmatch(r"manual:[A-Za-z0-9_-]+", value):
            raise serializers.ValidationError("须为 manual:<字母数字连字符或下划线>")
        return value

    def validate_source_url(self, value):
        if value is not None:
            from django.core.validators import URLValidator
            from django.core.exceptions import ValidationError
            try:
                URLValidator(schemes=["http", "https"])(value)
            except ValidationError:
                raise serializers.ValidationError("须为 HTTP(S) 阅读链接") from None
        return value

    def validate_authorization_status(self, value):
        if value != "confirmed":
            raise DomainError("AUTHORIZATION_REQUIRED", "导入前须确认授权", fields={"authorization_status": ["授权未确认"]})
        return value


class JobSummarySerializer(serializers.Serializer):
    source_id = serializers.UUIDField()
    import_job_id = serializers.UUIDField()
    build_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["pending", "running", "succeeded", "failed"])
    review_status = serializers.ChoiceField(choices=["pending", "approved", "rejected"])
    review_method = serializers.ChoiceField(choices=["auto", "manual"], allow_null=True)
    is_current = serializers.BooleanField()
    reused = serializers.BooleanField()
    error_code = serializers.CharField(allow_null=True)


class EvidencePreviewSerializer(serializers.Serializer):
    evidence_id = serializers.UUIDField()
    ordinal = serializers.IntegerField()
    body = serializers.CharField(trim_whitespace=False)
    retrieval_text = serializers.CharField(trim_whitespace=False)
    knowledge_type = serializers.CharField()
    evidence_role = serializers.CharField()
    context_role = serializers.CharField()
    locator = serializers.JSONField()
    structured_fields = serializers.JSONField()
    warnings = serializers.ListField(child=serializers.CharField())


class ContextPreviewSerializer(serializers.Serializer):
    context_id = serializers.UUIDField()
    ordinal = serializers.IntegerField()
    title = serializers.CharField()
    body = serializers.CharField(trim_whitespace=False)
    scope_fields = serializers.JSONField()
    field_sources = serializers.JSONField()
    locator = serializers.JSONField()
    knowledge_types = serializers.ListField(child=serializers.CharField())
    warnings = serializers.ListField(child=serializers.CharField())
    children = EvidencePreviewSerializer(many=True)


class JobReportSerializer(JobSummarySerializer):
    input = ImportSnapshotSerializer()
    quality_report = serializers.JSONField()
    contexts = ContextPreviewSerializer(many=True)
    current_step = serializers.CharField()
    attempt_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    started_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    error_detail = serializers.CharField(allow_null=True)


class ReviewSerializer(StrictSerializer):
    decision = StrictChoice(choices=["approved", "rejected"])
    note = StrictString(max_length=2000)


class SourcePatchSerializer(StrictSerializer):
    source_url = StrictString(max_length=2048, allow_null=True, required=False)
    visibility = StrictChoice(choices=["public", "internal"], required=False)
    authorization_status = StrictChoice(choices=["confirmed", "pending", "revoked"], required=False)
    authorization_note = StrictString(max_length=2000, required=False)
    status = StrictChoice(choices=["active", "disabled"], required=False)
    validate_source_url = SourceImportSerializer.validate_source_url

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("PATCH 至少需要一个可维护字段")
        return attrs


class SourceResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    source_type = serializers.CharField()
    canonical_locator = serializers.CharField()
    source_url = serializers.CharField(allow_null=True)
    visibility = serializers.CharField()
    authorization_status = serializers.CharField()
    authorization_note = serializers.CharField()
    status = serializers.CharField()
    current_build_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class CitationSerializer(serializers.Serializer):
    evidence_id = serializers.UUIDField()
    context_role = serializers.CharField()
    knowledge_type = serializers.CharField()
    evidence_role = serializers.CharField()
    locator = serializers.JSONField()


class ContextResponseSerializer(serializers.Serializer):
    context_id = serializers.UUIDField()
    title = serializers.CharField()
    text = serializers.CharField(trim_whitespace=False)
    scope_fields = serializers.JSONField()
    source_id = serializers.UUIDField()
    source_title = serializers.CharField()
    source_url = serializers.CharField(allow_null=True)
    build_id = serializers.UUIDField()
    content_hash = serializers.CharField()
    source_date = serializers.DateField(allow_null=True)
    source_type = serializers.CharField()
    document_schema = serializers.CharField()
    schema_version = serializers.IntegerField()
    knowledge_types = serializers.ListField(child=serializers.CharField())
    locator = serializers.JSONField()
    field_sources = serializers.JSONField()
    citations = CitationSerializer(many=True)
    match_status = serializers.CharField()
    warnings = serializers.ListField(child=serializers.CharField())
    flags = serializers.ListField(child=serializers.CharField())


class EvidenceResponseSerializer(serializers.Serializer):
    evidence_id = serializers.UUIDField()
    context_id = serializers.UUIDField()
    body = serializers.CharField(trim_whitespace=False)
    knowledge_type = serializers.CharField()
    evidence_role = serializers.CharField()
    context_role = serializers.CharField()
    locator = serializers.JSONField()
    structured_fields = serializers.JSONField()
    warnings = serializers.ListField(child=serializers.CharField())
    context = ContextResponseSerializer()
