"""标准化导入契约。HTTP 与未来预处理插件复用同一校验。"""
from dataclasses import asdict

from rest_framework import serializers

from contracts.types import ContextDraft, EvidenceDraft, ProcessedDocument, SourceSpec


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("必须是 JSON 对象")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "未知字段" for key in sorted(unknown)})
        return super().to_internal_value(data)


class TextField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str) or "\x00" in data:
            raise serializers.ValidationError("必须是不含空字节的文本")
        try:
            data.encode("utf-8")
        except UnicodeError:
            raise serializers.ValidationError("必须是合法 UTF-8 文本") from None
        value = super().to_internal_value(data)
        if not value.strip():
            raise serializers.ValidationError("文本不能为空")
        return value


class EvidenceSerializer(StrictSerializer):
    key = TextField(max_length=100)
    body = TextField(trim_whitespace=False, max_length=32000)
    locator = serializers.DictField(default=dict)
    metadata = serializers.DictField(default=dict)
    warnings = serializers.ListField(child=TextField(max_length=500), default=list)


class ContextSerializer(StrictSerializer):
    key = TextField(max_length=100)
    title = TextField(max_length=200)
    body = TextField(trim_whitespace=False, max_length=100000)
    locator = serializers.DictField(default=dict)
    metadata = serializers.DictField(default=dict)
    warnings = serializers.ListField(child=TextField(max_length=500), default=list)
    children = EvidenceSerializer(many=True, allow_empty=False, max_length=100)

    def validate(self, data):
        keys = [child["key"] for child in data["children"]]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError({"children": "同一父段内 key 不能重复"})
        if any(child["body"] not in data["body"] for child in data["children"]):
            raise serializers.ValidationError({"children": "子块正文必须来自所属父段"})
        return data


class DocumentSerializer(StrictSerializer):
    title = TextField(max_length=200)
    document_schema = serializers.RegexField(r"^[a-z][a-z0-9_]*$", max_length=64)
    schema_version = serializers.IntegerField(min_value=1, default=1)
    source_date = serializers.DateField(allow_null=True, default=None)
    metadata = serializers.DictField(default=dict)
    warnings = serializers.ListField(child=TextField(max_length=500), default=list)
    contexts = ContextSerializer(many=True, allow_empty=False, max_length=100)

    def validate(self, data):
        keys = [context["key"] for context in data["contexts"]]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError({"contexts": "同一文档内 key 不能重复"})
        if sum(len(context["children"]) for context in data["contexts"]) > 1000:
            raise serializers.ValidationError({"contexts": "单次导入最多 1000 个子块"})
        return data


class SourceSerializer(StrictSerializer):
    source_type = serializers.RegexField(r"^[a-z][a-z0-9_]*$", max_length=64)
    canonical_locator = TextField(max_length=200)
    visibility = serializers.ChoiceField(choices=["public", "internal"])
    source_url = serializers.URLField(max_length=2048, allow_null=True, default=None)


class SourceImportSerializer(StrictSerializer):
    source = SourceSerializer()
    document = DocumentSerializer()


def to_document(data):
    values = dict(data)
    values["contexts"] = [ContextDraft(**{
        **parent, "children": [EvidenceDraft(**child) for child in parent["children"]],
    }) for parent in data["contexts"]]
    return ProcessedDocument(**values)


def validate_document(document):
    """插件输出也走边界校验，不要求插件了解 ORM。"""
    serializer = DocumentSerializer(data=asdict(document))
    serializer.is_valid(raise_exception=True)
    return to_document(serializer.validated_data)


def import_dtos(data):
    return SourceSpec(**data["source"]), to_document(data["document"])
