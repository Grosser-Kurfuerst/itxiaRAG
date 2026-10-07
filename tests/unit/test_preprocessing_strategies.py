from dataclasses import asdict

import pytest

from contracts.errors import DomainError
from contracts.serializers import DocumentSerializer
from contracts.types import RawDocument
from ingestion.parsers import MarkdownParser
from ingestion.strategies import ExperienceCaseStrategy, PurchaseGuideStrategy, ReviewStrategy


def parse(text, **metadata):
    raw = RawDocument(text.encode(), "text/markdown", metadata)
    return MarkdownParser().parse(raw), raw


def test_review_has_one_parent_with_semantic_columns_and_atomic_thermal_conditions():
    blocks, raw = parse("# GT 16\n\n## 配置\n\n酷睿处理器\n\n## 优缺点\n\n优点：安静\n\n"
                        "## 散热分析\n\n室温25℃、双烤30分钟。\n\nCPU 80℃。")
    parent, = ReviewStrategy().build(blocks, raw)
    assert parent.title == "GT 16"
    assert len(parent.children) == 3
    assert parent.children[-1].atomic
    assert "室温25℃" in parent.children[-1].body and "80℃" in parent.children[-1].body
    assert all(child.body in parent.body for child in parent.children)


def test_explicit_multi_laptop_boundaries_do_not_mix_entities():
    blocks, raw = parse("# 横评\n\n## Laptop A\n\n### 配置\n\n16GB\n\n## Laptop B\n\n### 配置\n\n32GB",
                        entity_headings=["Laptop A", "Laptop B"])
    result = ReviewStrategy().build(blocks, raw)
    assert [p.title for p in result] == ["Laptop A", "Laptop B"]
    assert "32GB" not in result[0].body and "16GB" not in result[1].body
    bad = RawDocument(raw.content, raw.media_type, {"entity_headings": ["Laptop C"]})
    with pytest.raises(DomainError, match="未在原文找到"):
        ReviewStrategy().build(blocks, bad)


def test_guide_separates_model_cards_from_budget_and_keeps_faq():
    blocks, raw = parse("# 小白指南\n\n## 价格警告\n\n仅供本期参考。\n\n## 5000～6000元\n\n"
                        "### Laptop A\n\n### 配置\n\n16GB\n\n### 购买建议\n\n轻办公推荐，不适合游戏。\n\n"
                        "### Laptop B\n\n32GB\n\n## FAQ\n\n价格会变吗？")
    parents = PurchaseGuideStrategy().build(blocks, raw)
    model_a = next(p for p in parents if p.title == "Laptop A")
    model_b = next(p for p in parents if p.title == "Laptop B")
    assert model_a.metadata["budget"] == model_b.metadata["budget"] == "5000～6000元"
    assert "32GB" not in model_a.body
    assert "不适合游戏" in model_a.children[-1].body
    assert len(model_a.children) == 2
    assert model_a.metadata["global_guidance"] == ["价格警告\n\n仅供本期参考。"]
    assert model_a.warnings
    assert parents[-1].title == "FAQ"
    assert "budget" not in parents[-1].metadata


def test_experience_cases_keep_symptoms_and_resolution_within_each_parent():
    blocks, raw = parse("# 维修经验\n\n## 黑屏案例\n\n### 现象\n\n风扇正常。\n\n"
                        "### 处理与结果\n\n更换排线后恢复。\n\n## 无线案例\n\n重新安装驱动。")
    parents = ExperienceCaseStrategy().build(blocks, raw)
    assert [p.title for p in parents] == ["黑屏案例", "无线案例"]
    assert "风扇正常" in parents[0].body and "更换排线" in parents[0].body
    assert "驱动" not in parents[0].body


def test_duplicate_headings_have_unique_keys_and_body_edits_keep_keys():
    strategy = ExperienceCaseStrategy()
    original = strategy.build(*parse("# Doc\n\n## 案例\n\n原文\n\n## 案例\n\n另一个原文"))
    edited = strategy.build(*parse("# Doc\n\n## 案例\n\n更新正文\n\n## 案例\n\n另一个原文"))
    assert len({p.key for p in original}) == 2
    assert [p.key for p in original] == [p.key for p in edited]


def test_all_strategies_keep_every_parsed_content_block_and_produce_valid_dto():
    for strategy in [ReviewStrategy(), PurchaseGuideStrategy(), ExperienceCaseStrategy()]:
        blocks, raw = parse("# 标题\n\n前言  \n下一行\n\n## 配置\n\n| 项目 | 值 |\n| --- | --- |\n| 内存 | 16GB |")
        parents = strategy.build(blocks, raw)
        payload = {"title": "标题", "document_schema": "test_note", "contexts": [
            {**asdict(p), "children": [{k: v for k, v in asdict(child).items() if k != "atomic"} for child in p.children]}
            for p in parents
        ]}
        serializer = DocumentSerializer(data=payload)
        assert serializer.is_valid(), serializer.errors
        for block in blocks[1:]:
            assert any(block.text in parent.body for parent in parents)


def test_chunker_counts_parent_title_and_rejects_overlong_atomic_result():
    from ingestion.chunking import BudgetChunker

    blocks, raw = parse("# 很长的父段标题\n\n## 散热分析\n\n室温25℃测试条件和 CPU 80℃结果")
    context = ReviewStrategy().build(blocks, raw)[0]
    with pytest.raises(DomainError, match="完整测试条件"):
        BudgetChunker(max_input_units=8).chunk([context])


def test_priced_model_title_remains_a_card_with_original_budget_and_global_guidance():
    blocks, raw = parse("# 指南\n\n## 价格警告\n\n价格随时间变化。\n\n## 5000～6000元\n\n"
                        "### Laptop A（5499元）\n\n16GB 内存，适合轻办公。\n\n### Laptop B（5999元）\n\n32GB。")
    parents = PurchaseGuideStrategy().build(blocks, raw)
    cards = [p for p in parents if "entity_title" in p.metadata]
    assert [p.title for p in cards] == ["Laptop A（5499元）", "Laptop B（5999元）"]
    assert all(p.metadata["budget"] == "5000～6000元" for p in cards)
    assert all(p.metadata["global_guidance"] == ["价格警告\n\n价格随时间变化。"] for p in cards)
    assert all(p.warnings for p in cards)
    flat_blocks, flat_raw = parse("# 指南\n\n## 价格警告\n\n价格会变。\n\n## Laptop A（5499元）\n\n轻办公。")
    flat_card = PurchaseGuideStrategy().build(flat_blocks, flat_raw)[-1]
    assert "budget" not in flat_card.metadata
    assert flat_card.metadata["global_guidance"] and flat_card.warnings


def test_nested_thermal_headings_keep_conditions_and_results_in_one_atomic_evidence():
    from ingestion.chunking import BudgetChunker

    blocks, raw = parse("# Laptop A\n\n## 散热分析\n\n### 测试条件\n\n室温25℃，双烤30分钟。\n\n"
                        "### 测试结果\n\nCPU 80℃。\n\n## 续航\n\n9 小时。")
    parent, = ReviewStrategy().build(blocks, raw)
    assert len(parent.children) == 2
    thermal = parent.children[0]
    assert thermal.atomic and "室温25℃" in thermal.body and "CPU 80℃" in thermal.body
    with pytest.raises(DomainError) as error:
        BudgetChunker(max_input_units=40).chunk([parent])
    assert error.value.code == "SEMANTIC_UNIT_TOO_LARGE"

