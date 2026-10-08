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


def test_review_requires_machine_title_and_builds_one_machine_parent():
    text = ("# 评测文章标题\n\n## 配置\n\n酷睿处理器\n\n## 优缺点\n\n优点：安静\n\n"
            "## 散热分析\n\n室温25℃、双烤30分钟。\n\nCPU 80℃。")
    blocks, raw = parse(text, entity_title="GT 16")
    parent, = ReviewStrategy().build(blocks, raw)
    assert parent.title == "GT 16"
    assert "评测文章标题" not in parent.body and "CPU 80℃" in parent.body
    # 短评测合并为一个检索块；子块不再标注小节语义或不可拆分。
    child, = parent.children
    assert child.key == "evidence-chunk-1" and child.body == parent.body and not child.atomic
    for metadata in [{}, {"title": "文章标题"}, {"entity_title": "  "}]:
        blocks, raw = parse(text, **metadata)
        with pytest.raises(DomainError) as error:
            ReviewStrategy().build(blocks, raw)
        assert error.value.code == "ENTITY_TITLE_REQUIRED"


def test_review_chunks_merge_paragraphs_and_break_only_at_section_labels_or_target_length():
    blocks, raw = parse(
        "开头介绍这台电脑。\n\n它的配置如下：\n\n处理器 Core 5 205H。\n\n**屏幕方面，实测色域 96.9%sRGB。**\n\n"
        "亮度约 443nits。\n\n**缺点！**\n\n1，机身厚重\n\n2，硬盘较慢\n\n3，品牌一般\n\n"
        "【散热分析】\n\n室温 25℃。\n\nCPU 80℃，功耗 45W。\n\n显卡 68.5℃，功耗 95W。\n\n结语很短。",
        entity_title="GT 16",
    )
    parent, = ReviewStrategy(target_chars=60, min_chars=10).build(blocks, raw)
    bodies = [child.body for child in parent.children]
    assert [child.key for child in parent.children] == [f"evidence-chunk-{n}" for n in range(1, len(bodies) + 1)]
    assert all(body in parent.body and not child.atomic for body, child in zip(bodies, parent.children))

    def chunk_of(text):
        return next(body for body in bodies if text in body)

    # 引导句与后文、整句加粗的数据与前文、编号条目都留在同一块。
    assert "处理器 Core 5 205H" in chunk_of("它的配置如下：")
    assert "开头介绍这台电脑" in chunk_of("屏幕方面")
    assert all(item in chunk_of("缺点！") for item in ["1，机身厚重", "2，硬盘较慢", "3，品牌一般"])
    # 栏目名开启新块，测试条件与结果在目标长度内保持完整。
    thermal = chunk_of("【散热分析】")
    assert thermal.startswith("【散热分析】")
    assert all(text in thermal for text in ["室温 25℃", "CPU 80℃", "显卡 68.5℃", "结语很短"])


def test_review_short_chunks_merge_only_within_limit_and_semicolon_lines_stay_together():
    def chunks(text, **options):
        blocks, raw = parse(text, entity_title="Laptop A")
        parent, = ReviewStrategy(**options).build(blocks, raw)
        return [child.body for child in parent.children]

    # 过短首块并入后一块，过短尾块并回前一块；目标长度按块文本（含段落间隔）计算。
    assert chunks("前言。\n\n【配置】\n\n处理器和显卡都比较新。\n\n【续航】\n\n日常办公约九小时左右。\n\n短尾。",
                  target_chars=20, min_chars=8) == [
        "前言。\n\n【配置】\n\n处理器和显卡都比较新。", "【续航】\n\n日常办公约九小时左右。\n\n短尾。"]
    # 合并后超过 target_chars + min_chars 时保留短块。
    assert chunks("【配置】\n\n处理器和显卡都比较新，内存够用。\n\n【续航】\n\n短。", target_chars=20, min_chars=8) == [
        "【配置】\n\n处理器和显卡都比较新，内存够用。", "【续航】\n\n短。"]
    # 以“；”结尾的数据与后续结果相连。
    assert chunks("噪音方面，日常环境 55.4dB；\n\n消声室内 49.2dB。\n\n其他内容比较长的一段话。",
                  target_chars=20, min_chars=0)[0] == "噪音方面，日常环境 55.4dB；\n\n消声室内 49.2dB。"
    # 正文中出现一级标题后，二级栏目仍然开启新块。
    assert chunks("前言。\n\n# 来酷 GT16\n\n## 配置\n\n16GB 内存。\n\n## 散热分析\n\n室温 25℃。", min_chars=0)[-1] == \
        "散热分析\n\n室温 25℃。"


def test_review_nested_headings_stay_with_section_and_long_chunks_are_split_not_rejected():
    from ingestion.chunking import BudgetChunker

    blocks, raw = parse("# Laptop A\n\n## 散热分析\n\n### 测试条件\n\n室温25℃，双烤30分钟。\n\n"
                        "### 测试结果\n\nCPU 80℃。\n\n## 续航\n\n" + "日常办公脚本续航约 9 小时。" * 10,
                        entity_title="Laptop A")
    # 关闭短块合并，只验证子标题不断块、同级栏目断块。
    parent, = ReviewStrategy(min_chars=0).build(blocks, raw)
    assert len(parent.children) == 2
    thermal, battery = parent.children
    assert "室温25℃" in thermal.body and "CPU 80℃" in thermal.body
    assert battery.body.startswith("续航")
    chunked, = BudgetChunker(max_input_units=60).chunk([parent])
    assert len(chunked.children) > 2
    assert all(len(f"{chunked.title}\n{child.body}".encode()) <= 60 for child in chunked.children)


def test_review_drops_images_without_alt_but_keeps_described_images_and_warning():
    from ingestion.chunking import BudgetChunker
    from ingestion.parsers import HtmlParser
    from ingestion.preprocessing import (
        BuildDocumentStep, ChunkStep, ParseStep, PreprocessPipeline, StructureStep, ValidateStep,
    )

    pipeline = PreprocessPipeline([
        ParseStep(HtmlParser()), StructureStep(ReviewStrategy()), ChunkStep(BudgetChunker()),
        BuildDocumentStep(document_schema="product_review"), ValidateStep(),
    ])
    # 微信默认 alt“图片”、同一段落内的多张图片都视为没有文字说明。
    html = ('<div id="js_content"><p>配置：16GB</p><p><img src="a.png"></p><section><img alt="图片"></section>'
            '<p><img src="b.png"><br><img alt=" 图片 "></p><p><img alt="接口分布图"></p><p>续航约 9 小时。</p></div>')
    document = pipeline.process(RawDocument(html.encode(), "text/html", {"entity_title": "Laptop A"}))
    parent, = document.contexts
    assert parent.body == "配置：16GB\n\n[图片：接口分布图]\n\n续航约 9 小时。"
    assert any("图片" in warning for warning in document.warnings)


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
        blocks, raw = parse("# 标题\n\n前言  \n下一行\n\n## 配置\n\n| 项目 | 值 |\n| --- | --- |\n| 内存 | 16GB |",
                            entity_title="Laptop A")
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

    blocks, raw = parse("# 经验\n\n## 很长的父段标题\n\n### 测试结果\n\n室温25℃测试条件和 CPU 80℃结果")
    context = ExperienceCaseStrategy().build(blocks, raw)[0]
    assert context.children[0].atomic
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


