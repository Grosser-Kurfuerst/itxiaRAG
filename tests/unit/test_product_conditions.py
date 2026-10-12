from types import SimpleNamespace

import pytest

from contracts.products import PORTS, ConditionsSerializer
from products.conditions import CONDITIONS, diagnostics, evaluate, match, unknown_counts


def laptop(key, **fields):
    values = {name: None for name, _ in CONDITIONS.values()}
    values.update(key=key, brand="联想", ports=dict.fromkeys(PORTS, False))
    return SimpleNamespace(**{**values, **fields})


GAMING = laptop("游戏本", price_cny=9999, weight_kg=2.5, screen_inch=16, battery_hours=6, has_dgpu=True,
                gpu="RTX 5070", is_gaming=True, panel="lcd", ports={**dict.fromkeys(PORTS, False), "hdmi": True})
THIN = laptop("轻薄本", brand="华为", price_cny=7999, weight_kg=1.2, screen_inch=14, has_dgpu=False, panel="oled")


@pytest.mark.parametrize("name, value, expected", [
    ("price_min", 9999, True), ("price_max", 9998, False),
    ("weight_max", 2.5, True), ("screen_min", 16.1, False), ("screen_max", 16, True),
    ("battery_min", 6, True), ("battery_min", 6.5, False),
    ("gpu_in", ["RTX 5060", "RTX 5070"], True), ("gpu_in", ["RTX 5060"], False),
    ("has_dgpu", True, True), ("is_gaming", False, False), ("panel", "oled", False),
    ("ports", ["hdmi"], True), ("ports", ["hdmi", "rj45"], False),
    ("brands", ["联想", "华为"], True), ("brands", ["华为"], False),
])
def test_each_condition(name, value, expected):
    assert evaluate(GAMING, name, value) is expected


def test_null_field_is_unknown_except_gpu_of_confirmed_integrated_laptop():
    assert evaluate(THIN, "battery_min", 1) is None
    assert evaluate(THIN, "is_gaming", False) is None
    assert evaluate(THIN, "gpu_in", ["RTX 5060"]) is False
    assert evaluate(laptop("未知显卡"), "gpu_in", ["RTX 5060"]) is None


def test_unknown_counts_only_laptops_blocked_by_one_null_field():
    no_battery = laptop("缺续航", price_cny=6000, weight_kg=1.3)
    no_battery_too_heavy = laptop("缺续航且过重", price_cny=6000, weight_kg=2.0)
    no_battery_or_price = laptop("缺续航与价格", weight_kg=1.3)
    no_price = laptop("只缺价格", weight_kg=1.3, battery_hours=10)
    specs = [THIN, no_battery, no_battery_too_heavy, no_battery_or_price, no_price]
    conditions = {"price_min": 5000, "price_max": 8000, "weight_max": 1.5, "battery_min": 8}

    assert match(specs, conditions) == []
    assert unknown_counts(specs, conditions) == {"battery_hours": 2, "price_cny": 1}
    assert diagnostics(specs, conditions) == {"total": 5, "satisfied": {
        "price_min": 3, "price_max": 3, "weight_max": 4, "battery_min": 1}}


def test_empty_conditions_match_all():
    assert match([GAMING, THIN], {}) == [GAMING, THIN]
    assert unknown_counts([GAMING, THIN], {}) == {}


def test_every_request_condition_has_a_rule():
    assert set(ConditionsSerializer().fields) == set(CONDITIONS)
