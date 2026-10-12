import json
from pathlib import Path

import pytest

from contracts.products import PORTS, ProductSpecSerializer, normalize_gpu

SPEC_FILE = Path(__file__).resolve().parents[2] / "products/specs/bibar.json"


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
