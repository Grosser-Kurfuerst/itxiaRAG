"""机型规格契约：规格文件的记录格式与取值口径，见机型规格库方案 5.1、5.3 节。"""
import re

from rest_framework import serializers

from contracts.serializers import StrictSerializer, TextField

PRICE_KINDS = ["launch", "reference", "subsidy", "predicted"]
PANELS = ["oled", "lcd", "miniled"]
RAM_KINDS = ["slots", "soldered"]
PORTS = ["usb_a", "usb_c", "video_out", "hdmi", "rj45", "card_reader", "thunderbolt", "oculink"]


def normalize_gpu(name):
    """统一 NVIDIA 独显写法，如 rtx5070 ti → RTX 5070Ti；其他型号只合并多余空白。"""
    nvidia = re.fullmatch(r"(RTX|GTX)(\d+)(TI)?", re.sub(r"\s+", "", name).upper())
    if nvidia is None:
        return " ".join(name.split())
    return f"{nvidia[1]} {nvidia[2]}{'Ti' if nvidia[3] else ''}"


def compact_text(text):
    """引用校验前去掉空白，避免换行、空格差异导致误报。"""
    return re.sub(r"\s+", "", text)


class GpuField(serializers.CharField):
    def to_internal_value(self, data):
        return normalize_gpu(super().to_internal_value(data))


class PortsSerializer(StrictSerializer):
    def get_fields(self):
        return {name: serializers.BooleanField() for name in PORTS}


class WebEvidenceSerializer(StrictSerializer):
    """联网补充的引用：只检查格式，来源是否可靠由人工核对。"""
    source = serializers.RegexField(r"^https?://\S+$", max_length=2048)
    quote = TextField(max_length=2000)


class ProductSpecSerializer(StrictSerializer):
    key = TextField(max_length=200)
    brand = TextField(max_length=50)
    price_cny = serializers.FloatField(min_value=1, allow_null=True, default=None)
    price_kind = serializers.ChoiceField(PRICE_KINDS, allow_null=True, default=None)
    price_date = serializers.DateField(allow_null=True, default=None)
    weight_kg = serializers.FloatField(min_value=0.1, max_value=10, allow_null=True, default=None)
    screen_inch = serializers.FloatField(min_value=5, max_value=30, allow_null=True, default=None)
    panel = serializers.ChoiceField(PANELS, allow_null=True, default=None)
    cpu = TextField(max_length=100, allow_null=True, default=None)
    has_dgpu = serializers.BooleanField(allow_null=True, default=None)
    gpu = GpuField(max_length=50, allow_null=True, default=None)
    ram_gb = serializers.IntegerField(min_value=1, allow_null=True, default=None)
    ram_upgradable = serializers.ChoiceField(RAM_KINDS, allow_null=True, default=None)
    storage_gb = serializers.IntegerField(min_value=1, allow_null=True, default=None)
    battery_hours = serializers.FloatField(min_value=0, max_value=48, allow_null=True, default=None)
    is_gaming = serializers.BooleanField(allow_null=True, default=None)
    ports = PortsSerializer()
    ports_text = serializers.CharField(max_length=5000, allow_blank=True, default="")
    extra = serializers.DictField(default=dict)
    evidence = serializers.DictField(default=dict)
    note = serializers.CharField(max_length=500, allow_blank=True, default="")

    def validate_evidence(self, value):
        """原文引用是非空字符串，联网补充是 {source, quote}；键必须是规格字段名。"""
        for name, quote in value.items():
            if name not in self.fields or name in {"key", "evidence"}:
                raise serializers.ValidationError({name: "不是规格字段"})
            if isinstance(quote, str):
                if not quote.strip():
                    raise serializers.ValidationError({name: "引用不能为空"})
                continue
            if not isinstance(quote, dict):
                raise serializers.ValidationError({name: "必须是原文引用字符串或 {source, quote} 对象"})
            web = WebEvidenceSerializer(data=quote)
            if not web.is_valid():
                raise serializers.ValidationError({name: web.errors})
        return value

    def validate(self, data):
        if data["gpu"] is not None and data["has_dgpu"] is not True:
            raise serializers.ValidationError({"gpu": "填写独显型号时 has_dgpu 必须为 true"})
        if data["price_cny"] is None and data["price_kind"] is not None:
            raise serializers.ValidationError({"price_kind": "没有价格时不能填写价格口径"})
        return data
