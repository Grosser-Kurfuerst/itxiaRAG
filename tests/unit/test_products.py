import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts.products import BRANDS, GPUS, PORTS, ProductSpecSerializer, RecommendInput, normalize_gpu

ROOT = Path(__file__).resolve().parents[2]
SPEC_FILE = ROOT / "products/specs/bibar.json"
TOOL_FILE = ROOT / "products/tool-definitions.md"


def validate_spec(**fields):
    serializer = ProductSpecSerializer(data={"key": "笔记本 A", "brand": "示例",
                                             "ports": dict.fromkeys(PORTS, False), **fields})
    return serializer.validated_data if serializer.is_valid() else serializer.errors


@pytest.mark.parametrize("name", ["RTX 5070Ti", "rtx5070ti", "RTX 5070 Ti", " RTX5070TI "])
def test_normalize_gpu_unifies_spelling(name):
    assert normalize_gpu(name) == "RTX 5070Ti"


@pytest.mark.parametrize("name, expected", [("RTX 4060 Laptop", "RTX 4060 Laptop"), ("Arc  A770M", "Arc A770M")])
def test_normalize_gpu_keeps_other_models(name, expected):
    assert normalize_gpu(name) == expected


def test_spec_defaults_unknown_fields_to_null_and_normalizes_gpu():
    data = validate_spec(has_dgpu=True, gpu="rtx 5060")
    assert data["gpu"] == "RTX 5060"
    assert data["battery_hours"] is None and data["is_gaming"] is None and data["evidence"] == {}


@pytest.mark.parametrize("fields, field", [
    ({"has_dgpu": False, "gpu": "RTX 5060"}, "gpu"),
    ({"gpu": "RTX 5060"}, "gpu"),
    ({"price_kind": "reference"}, "price_kind"),
    ({"panel": "ips"}, "panel"),
    ({"ports": {"usb_a": True}}, "ports"),
    ({"weight": 1.2}, "weight"),
    ({"price_cny": "inf"}, "price_cny"),
    ({"evidence": {"weight": "重量 1.2kg"}}, "evidence"),
    ({"evidence": {"weight_kg": " "}}, "evidence"),
    ({"evidence": {"weight_kg": 2.23}}, "evidence"),
    ({"evidence": {"cpu": {"source": "ftp://example.com", "quote": "Ultra 7"}}}, "evidence"),
])
def test_spec_rejects_invalid_values(fields, field):
    assert field in validate_spec(**fields)


def test_spec_accepts_review_and_web_evidence():
    evidence = {"weight_kg": "重量 1.2kg", "cpu": {"source": "https://example.com/spec", "quote": "Ultra 7 255H"}}
    assert validate_spec(evidence=evidence)["evidence"] == evidence


def test_committed_spec_file_is_valid():
    records = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    errors = {record["key"]: s.errors for record in records if not (s := ProductSpecSerializer(data=record)).is_valid()}
    assert errors == {}
    assert len({record["key"] for record in records}) == len(records)


def validate_request(data):
    return RecommendInput.model_validate(data).model_dump(exclude_none=True)


def test_recommend_request_defaults_and_normalizes_gpu():
    assert validate_request({}) == {"conditions": {}, "preference": "", "top_k": 5}
    data = validate_request({"conditions": {"gpu_in": ["rtx5070 ti"], "ports": ["hdmi"], "panel": "oled"}})
    assert data["conditions"] == {"gpu_in": ["RTX 5070Ti"], "ports": ["hdmi"], "panel": "oled"}


def test_recommend_request_treats_null_as_omitted():
    assert validate_request({"conditions": None, "preference": None, "top_k": None}) == {
        "conditions": {}, "preference": "", "top_k": 5}
    assert validate_request({"conditions": {"price_min": None, "has_dgpu": False, "gpu_in": None}}) == {
        "conditions": {"has_dgpu": False}, "preference": "", "top_k": 5}


def test_recommend_request_lists_enum_options_for_unknown_gpu_and_brand():
    with pytest.raises(ValidationError) as error:
        validate_request({"conditions": {"gpu_in": ["RTX 4090"], "brands": ["不存在"]}})
    errors = str(error.value)
    assert "RTX 4090" in errors and "RTX 5070" in errors and "RTX 5090" in errors
    assert "不存在" in errors and "雷蛇" in errors


@pytest.mark.parametrize("data", [
    {"conditions": {"thin_light": True}},
    {"conditions": {"price_min": 9000, "price_max": 8000}},
    {"conditions": {"ports": ["usb4"]}},
    {"conditions": {"gpu_in": []}},
    {"conditions": {"price_max": "nan"}},
    {"top_k": 21},
    {"query": "游戏本"},
    {"unknown": 1},
])
def test_recommend_request_rejects_invalid_values(data):
    with pytest.raises(ValidationError):
        validate_request(data)


def test_tool_prompt_and_enums_match_spec_file():
    text = TOOL_FILE.read_text(encoding="utf-8")
    prompt, = re.findall(r"```text\n(.*?)\n```", text, re.S)  # 评测脚本按这个约定读取提示词
    assert "```json\n" not in text
    records = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    assert set(GPUS) == {normalize_gpu(record["gpu"]) for record in records if record.get("gpu")}
    assert set(BRANDS) == {record["brand"] for record in records}
    assert " < ".join(GPUS) in prompt  # 提示词中的显卡档次与 enum 顺序一致
