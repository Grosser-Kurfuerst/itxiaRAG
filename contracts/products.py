"""机型规格契约：规格文件的记录格式与推荐请求，见机型规格库方案 5.1、5.3、6.1 节。"""
import math
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, Field, model_validator
from pydantic_core import PydanticCustomError
from rest_framework import serializers

from contracts.requests import RequestModel, empty_if_null, strip_text
from contracts.serializers import StrictSerializer, TextField

PRICE_KINDS = ["launch", "reference", "subsidy", "predicted"]
PANELS = ("oled", "lcd", "miniled")
RAM_KINDS = ["slots", "soldered"]
PORTS = ("usb_a", "usb_c", "video_out", "hdmi", "rj45", "card_reader", "thunderbolt", "oculink")
GPUS = ("RTX 3050", "RTX 5060", "RTX 5070", "RTX 5070Ti", "RTX 5080", "RTX 5090")
BRANDS = (
    "ALIENWARE", "LG", "ROG", "ThinkPad", "七彩虹", "华为", "华硕", "小米", "微星", "微软",
    "惠普", "机械师", "机械革命", "神舟", "红米", "联想", "苹果", "荣耀", "雷神", "雷蛇",
)


def normalize_gpu(name):
    """统一 NVIDIA 独显写法，如 rtx5070 ti → RTX 5070Ti；其他型号只合并多余空白。"""
    nvidia = re.fullmatch(r"(RTX|GTX)(\d+)(TI)?", re.sub(r"\s+", "", name).upper())
    if nvidia is None:
        return " ".join(name.split())
    return f"{nvidia[1]} {nvidia[2]}{'Ti' if nvidia[3] else ''}"


def compact_text(text):
    """引用校验前去掉空白，避免换行、空格差异导致误报。"""
    return re.sub(r"\s+", "", text)


class FiniteFloatField(serializers.FloatField):
    """DRF 的 FloatField 接受 "nan"、"inf"，它们会绕过取值范围检查。"""

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            raise serializers.ValidationError("必须是有限数值")
        return value


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
    price_cny = FiniteFloatField(min_value=1, allow_null=True, default=None)
    price_kind = serializers.ChoiceField(PRICE_KINDS, allow_null=True, default=None)
    price_date = serializers.DateField(allow_null=True, default=None)
    weight_kg = FiniteFloatField(min_value=0.1, max_value=10, allow_null=True, default=None)
    screen_inch = FiniteFloatField(min_value=5, max_value=30, allow_null=True, default=None)
    panel = serializers.ChoiceField(PANELS, allow_null=True, default=None)
    cpu = TextField(max_length=100, allow_null=True, default=None)
    has_dgpu = serializers.BooleanField(allow_null=True, default=None)
    gpu = GpuField(max_length=50, allow_null=True, default=None)
    ram_gb = serializers.IntegerField(min_value=1, allow_null=True, default=None)
    ram_upgradable = serializers.ChoiceField(RAM_KINDS, allow_null=True, default=None)
    storage_gb = serializers.IntegerField(min_value=1, allow_null=True, default=None)
    battery_hours = FiniteFloatField(min_value=0, max_value=48, allow_null=True, default=None)
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


def normalize_gpu_input(value):
    return normalize_gpu(value) if isinstance(value, str) else value


Gpu = Annotated[Literal[GPUS], BeforeValidator(normalize_gpu_input)]
Amount = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Preference = Annotated[
    str,
    Field(max_length=500, description="无法换算成条件的偏好，例如“性能释放强、散热好”。为空时按评测日期由新到旧排序。"),
    AfterValidator(strip_text),
]
RecommendTopK = Annotated[int, Field(ge=1, le=20, description="返回的机型数。")]


class Conditions(RequestModel):
    """只接受原子条件（方案 6.1 节）；“轻薄”“预算左右”等派生概念由上层换算。"""
    price_min: Annotated[Amount, Field(description="价格下限（元）。价格是评测时的价格，不是实时价格。")] = None
    price_max: Annotated[Amount, Field(description="价格上限（元）。")] = None
    weight_max: Annotated[Amount, Field(description="重量上限（kg）。")] = None
    screen_min: Annotated[Amount, Field(description="屏幕尺寸下限（英寸）。")] = None
    screen_max: Annotated[Amount, Field(description="屏幕尺寸上限（英寸）。")] = None
    battery_min: Annotated[
        Amount,
        Field(description="续航下限（小时），只指评测中“日常应用仿真”的成绩。许多机型没有该数据，没有数据视为不满足。"),
    ] = None
    gpu_in: Annotated[
        list[Gpu],
        Field(min_length=1, max_length=20, description="独显型号，满足其中之一即可；没有独显的机型不满足。"),
    ] = None
    has_dgpu: Annotated[bool, Field(description="是否有独立显卡。")] = None
    is_gaming: Annotated[
        bool,
        Field(description="是否游戏本：有 RTX 独显且定位为游戏本，创作本、全能本、商务本、双屏本除外。"),
    ] = None
    panel: Annotated[Literal[PANELS], Field(description="屏幕面板类型。")] = None
    ports: Annotated[
        list[Literal[PORTS]],
        Field(min_length=1, max_length=len(PORTS),
              description="必须全部具备的接口：usb_a、usb_c；video_out 为任一视频输出（HDMI、DP 或支持 DP 的 USB-C）；"
                          "hdmi；rj45 网口；card_reader 读卡器；thunderbolt 雷电或 USB4；oculink，TGX 接口也是 OCuLink。"),
    ] = None
    brands: Annotated[
        list[Literal[BRANDS]],
        Field(min_length=1, max_length=20,
              description="品牌，满足其中之一即可。子品牌 ROG、ThinkPad、红米单列，不归入华硕、联想、小米；"
                          "问母品牌的全部机型时连同子品牌一起列出。"),
    ] = None

    @model_validator(mode="after")
    def check_ranges(self):
        for low, high in [("price_min", "price_max"), ("screen_min", "screen_max")]:
            if getattr(self, low) is not None and getattr(self, high) is not None \
                    and getattr(self, low) > getattr(self, high):
                raise PydanticCustomError("range", "{low} 不能大于 {high}", {"low": low, "high": high})
        return self


ConditionsArg = Annotated[
    Conditions,
    BeforeValidator(empty_if_null),
    Field(default_factory=Conditions, description="硬条件，全部满足才入选；省略表示不过滤。"),
]


class RecommendInput(RequestModel):
    conditions: ConditionsArg
    preference: Preference = ""
    top_k: RecommendTopK = 5
