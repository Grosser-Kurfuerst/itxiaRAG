"""完整查询输入契约，以及迭代一的能力边界。"""
from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from contracts.errors import DomainError
from contracts.serializers import (ContextResponseSerializer, EmptyObjectField,
                                  StrictChoice, StrictInteger, StrictSerializer, StrictString)

KNOWLEDGE_TYPES = ["concept", "product_spec", "purchase_recommendation", "repair_case", "procedure", "faq"]
SCENARIOS = ["general", "purchase", "repair"]


class StrictList(serializers.ListField):
    def to_internal_value(self, data):
        if type(data) is not list:
            raise serializers.ValidationError("必须是数组")
        return super().to_internal_value(data)


class UniqueList(StrictList):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if len(set(value)) != len(value):
            raise serializers.ValidationError("数组不能包含重复值")
        return value


class StrictUUID(serializers.UUIDField):
    def to_internal_value(self, data):
        if type(data) is not str:
            raise serializers.ValidationError("必须是 UUID 字符串")
        return super().to_internal_value(data.strip())


@extend_schema_field({"type": "number", "minimum": 0, "multipleOf": 0.01})
class Amount(serializers.Field):
    def to_internal_value(self, data):
        if type(data) not in (int, float):
            raise serializers.ValidationError("金额必须是 JSON 数字")
        try:
            value = Decimal(str(data))
            if not value.is_finite() or value < 0 or value != value.quantize(Decimal("0.01")):
                raise ValueError
        except (ValueError, InvalidOperation):
            raise serializers.ValidationError("金额须非负、有限且最多两位小数") from None
        return value

    def to_representation(self, value):
        return float(value)


class BudgetSerializer(StrictSerializer):
    max = Amount()
    min = Amount(required=False)
    currency = StrictChoice(choices=["CNY"], default="CNY")

    def validate(self, attrs):
        if attrs["max"] <= 0:
            raise serializers.ValidationError({"max": ["预算上限须大于零"]})
        if attrs.get("min", 0) > attrs["max"]:
            raise serializers.ValidationError({"min": ["下限不能高于上限"]})
        return attrs


class ConfirmedContextSerializer(StrictSerializer):
    device_model = StrictString(max_length=200, allow_null=True, required=False)
    model_year = StrictInteger(min_value=1000, max_value=9999, allow_null=True, required=False)
    os_version = StrictString(max_length=200, allow_null=True, required=False)
    symptoms = StrictList(child=StrictString(max_length=200), max_length=20, required=False)
    checks_done = StrictList(child=StrictString(max_length=200), max_length=20, required=False)
    observed_results = StrictList(child=StrictString(max_length=200), max_length=20, required=False)
    budget = BudgetSerializer(allow_null=True, required=False)
    use_cases = UniqueList(child=StrictChoice(choices=["gaming", "office", "programming", "design", "video_editing", "other"]), max_length=20, required=False)
    use_case_note = StrictString(max_length=500, allow_null=True, required=False)
    portability = StrictChoice(choices=["required", "preferred", "irrelevant", "unknown"], allow_null=True, required=False)

    def validate(self, attrs):
        if "other" in attrs.get("use_cases", []) and not attrs.get("use_case_note"):
            raise serializers.ValidationError({"use_case_note": ["其他用途须补充说明"]})
        return attrs


class FiltersSerializer(StrictSerializer):
    knowledge_types = UniqueList(child=StrictChoice(choices=KNOWLEDGE_TYPES), min_length=1, max_length=6, required=False)
    source_ids = UniqueList(child=StrictUUID(), min_length=1, max_length=50, required=False)


class QuerySerializer(StrictSerializer):
    query = StrictString(max_length=2000)
    preprocess = StrictChoice(choices=["auto", "bypass"], default="auto")
    scenario = StrictChoice(choices=SCENARIOS, required=False)
    confirmed_context = ConfirmedContextSerializer(default=dict)
    filters = FiltersSerializer(default=dict)
    # 缺省值由活动 QueryProfile 提供，不在 Serializer 复制一份默认配置。
    top_k = StrictInteger(min_value=1, max_value=20, required=False)

    def validate(self, attrs):
        fields = {}
        if attrs.get("scenario", "general") != "general":
            fields["scenario"] = ["迭代一只支持 general"]
        if attrs["confirmed_context"]:
            fields["confirmed_context"] = ["条件匹配尚未开放"]
        if fields:
            raise DomainError("CAPABILITY_NOT_AVAILABLE", "本阶段尚未支持该能力", fields=fields)
        return attrs


class SearchContextSerializer(ContextResponseSerializer):
    matched_evidence_ids = serializers.ListField(child=serializers.UUIDField())


class QueryProcessingSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["noop", "bypassed", "applied", "fallback"])
    processor_id = serializers.CharField()
    effective_scenario = serializers.ChoiceField(choices=SCENARIOS)
    scenario_source = serializers.ChoiceField(choices=["caller", "inferred", "default"])
    suggested_context = EmptyObjectField()


class ExecutionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "degraded"])
    mode = serializers.ChoiceField(choices=["keyword"])
    warnings = serializers.ListField(child=serializers.CharField())


class SearchResponseSerializer(serializers.Serializer):
    query_id = serializers.UUIDField()
    index_profile_hash = serializers.RegexField(r"^[0-9a-f]{64}$")
    query_profile_hash = serializers.RegexField(r"^[0-9a-f]{64}$")
    feedback_available = serializers.BooleanField()
    execution = ExecutionSerializer()
    query_processing = QueryProcessingSerializer()
    result_status = serializers.ChoiceField(choices=["found", "no_result", "insufficient_evidence"])
    flags = serializers.ListField(child=serializers.CharField())
    missing_conditions = serializers.ListField(child=serializers.CharField())
    contexts = SearchContextSerializer(many=True)
