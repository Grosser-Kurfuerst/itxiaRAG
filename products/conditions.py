"""原子条件的判定（方案 6.2 节）。空值表示“未知”：未知不满足条件，但单独统计，供上层判断是否放宽。

候选最多是全部评测机型（几十到几百台），所以在内存中逐台判定，空值语义只在这里实现一次。
"""
from collections import Counter
import operator

# 条件名 → (规格字段, 判定函数)；判定函数的参数是 (字段值, 条件值)。
CONDITIONS = {
    "price_min": ("price_cny", operator.ge),
    "price_max": ("price_cny", operator.le),
    "weight_max": ("weight_kg", operator.le),
    "screen_min": ("screen_inch", operator.ge),
    "screen_max": ("screen_inch", operator.le),
    "battery_min": ("battery_hours", operator.ge),
    "gpu_in": ("gpu", lambda gpu, options: gpu in options),
    "has_dgpu": ("has_dgpu", operator.eq),
    "is_gaming": ("is_gaming", operator.eq),
    "panel": ("panel", operator.eq),
    "ports": ("ports", lambda ports, required: all(ports.get(name) for name in required)),
    "brands": ("brand", lambda brand, options: brand in options),
}


def evaluate(spec, name, value):
    """满足返回 True，不满足返回 False，字段为空返回 None（未知）。"""
    field, test = CONDITIONS[name]
    actual = getattr(spec, field)
    if actual is None:
        # 已确认没有独显时，显卡型号条件是明确不满足，而不是未知。
        return False if name == "gpu_in" and spec.has_dgpu is False else None
    return test(actual, value)


def match(specs, conditions):
    return [spec for spec in specs
            if all(evaluate(spec, name, value) is True for name, value in conditions.items())]


def unknown_counts(specs, conditions):
    """每个字段上“其他条件都满足、只是该字段为空”的机型数。"""
    counts = Counter()
    for spec in specs:
        results = {name: evaluate(spec, name, value) for name, value in conditions.items()}
        unknown_fields = {CONDITIONS[name][0] for name, result in results.items() if result is None}
        if len(unknown_fields) == 1 and False not in results.values():
            counts[unknown_fields.pop()] += 1
    return dict(counts)


def diagnostics(specs, conditions):
    """结果为空时给出单独满足每个条件的机型数；检索系统不自动放宽条件。"""
    return {"total": len(specs), "satisfied": {
        name: sum(evaluate(spec, name, value) is True for spec in specs) for name, value in conditions.items()}}
