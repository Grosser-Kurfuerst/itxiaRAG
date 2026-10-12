from datetime import date
from types import SimpleNamespace

from products.service import conclusions, rank


def chunk(key, *sections):
    return SimpleNamespace(key=key, metadata={"sections": list(sections)})


def laptop(key, context_id, source_date):
    return SimpleNamespace(key=key, review_context_id=context_id,
                           review_context=SimpleNamespace(source=SimpleNamespace(source_date=source_date)))


def test_conclusions_take_first_chunk_of_each_conclusion_section():
    children = [chunk("c1", "配置", "优点"), chunk("c2", "优点", "缺点"), chunk("c3", "购买建议"),
                chunk("c4", "购买建议"), chunk("c5", "猪王的良心结语"), chunk("c6", "总结")]
    assert [child.key for child in conclusions(children)] == ["c1", "c2", "c3"]


def test_conclusions_fall_back_to_last_chunk():
    assert [child.key for child in conclusions([chunk("c1", "配置"), chunk("c2"), chunk("c3")])] == ["c3"]
    assert conclusions([]) == []


def test_rank_puts_preference_hits_first_then_newest_reviews():
    old, new, undated, same_day = (laptop("B 旧", 1, date(2025, 1, 1)), laptop("C 新", 2, date(2026, 1, 1)),
                                   laptop("D 无日期", 3, None), laptop("A 新", 4, date(2026, 1, 1)))
    candidates = [old, new, undated, same_day]
    assert rank(candidates, {}) == [same_day, new, old, undated]
    assert rank(candidates, {3: [], 1: []}) == [undated, old, same_day, new]
