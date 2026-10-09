from dataclasses import replace

import pytest

from config import components
from contracts.types import RawDocument, evidence_input
from ingestion.chunking import BudgetChunker
from ingestion.enrichment import CalloutWarningStep, RetrievalPrefixStep, TimeExpressionStep
from ingestion.parsers import MarkdownParser, ParserRegistry
from ingestion.preprocessing import (
    BuildDocumentStep, ChunkStep, ParseStep, PreprocessContext, PreprocessPipeline,
    StructureStep, ValidateStep,
)
from ingestion.sections import SectionedDocumentStrategy, TUTORIAL


def structured(text, **metadata):
    raw = RawDocument(text.encode(), "text/markdown", {"title": "教程", **metadata})
    context = ParseStep(MarkdownParser()).process(PreprocessContext(raw))
    return StructureStep(SectionedDocumentStrategy(replace(TUTORIAL, min_parent_chars=0))).process(context)


def test_callouts_before_first_heading_go_to_document_and_others_to_parent():
    context = structured(
        "> [!WARNING]\n> 全文操作前备份。\n\n## 安装篇\n\n说明。\n\n"
        "> [!CAUTION]\n> 删除分区前确认已经备份数据。\n\n"
        "> [!NOTE]\n> 普通说明不作为风险提示。\n\n## 设置篇\n\n设置。",
    )
    CalloutWarningStep().process(context)
    assert context.warnings == ["【警告】\n全文操作前备份。"]
    assert context.units[0].warnings == []
    assert context.units[1].warnings == ["【警告】\n删除分区前确认已经备份数据。"]
    assert context.units[2].warnings == [] and context.stage == "units"


def test_callout_warnings_are_truncated_to_300_and_deduplicated():
    warning = "> [!WARNING]\n> " + "先备份。" * 100
    context = structured(warning + "\n\n" + warning + "\n\n## 安装篇\n\n" + warning + "\n\n" + warning)
    CalloutWarningStep().process(context)
    CalloutWarningStep().process(context)
    assert len(context.warnings) == len(context.units[-1].warnings) == 1
    assert len(context.warnings[0]) == len(context.units[-1].warnings[0]) == 300


def test_global_callout_deduplicates_against_raw_warnings_and_untitled_callouts_are_global():
    warning = "【警告】\n先备份。"
    context = structured("> [!WARNING]\n> 先备份。", warnings=[warning])
    CalloutWarningStep().process(context)
    assert context.warnings == [] and context.units[0].warnings == []
    context = structured("> [!WARNING]\n> 先备份。")
    CalloutWarningStep().process(context)
    assert context.warnings == [warning]


def test_global_callout_stays_global_when_intro_is_merged_into_section():
    raw = RawDocument("> [!WARNING]\n> 全局备份提醒。\n\n## 安装篇\n\n章节说明。".encode(),
                      "text/markdown", {"title": "教程"})
    document = components.preprocessors().process(raw, "tutorial", 1)
    parent, = document.contexts
    assert document.warnings == ["【警告】\n全局备份提醒。"]
    assert parent.title == "安装篇" and parent.warnings == []


@pytest.mark.parametrize("expression", ["目前（2022年初）", "截至 2023 年", "（2025.11 更新）", "(2025年更新)"])
def test_time_expressions_with_explicit_year_produce_parent_warning(expression):
    context = structured("## 安装篇\n\n" + expression + "可以这样操作。截至 2026 年仍可用。")
    TimeExpressionStep().process(context)
    TimeExpressionStep().process(context)
    assert context.units[0].warnings == [f"含时间限定表述‘{expression}’，请结合来源日期判断是否仍适用"]
    assert context.warnings == []


def test_time_warning_is_first_match_per_parent_and_ignores_yearless_text():
    context = structured("## 安装篇\n\n目前（2022年初）可用。截至 2025 年仍可用。\n\n"
                         "## 设置篇\n\n（2025.11 更新）设置步骤。\n\n## 附注\n\n目前可用，最近有更新，版本 2025。")
    TimeExpressionStep().process(context)
    assert len(context.units[0].warnings) == len(context.units[1].warnings) == 1
    assert "2022年初" in context.units[0].warnings[0] and "2025 年" not in context.units[0].warnings[0]
    assert "2025.11" in context.units[1].warnings[0] and context.units[2].warnings == []


def test_retrieval_prefix_excludes_parent_path_parts_and_combines_existing_header():
    context = structured("## 安装篇\n\n正文。", collection_path=["合成目录", "安装篇"])
    parent = context.units[0]
    context.units = [replace(parent, children=[replace(parent.children[0], retrieval_prefix="| 项目 | 值 |")])]
    RetrievalPrefixStep().process(context)
    assert context.units[0].children[0].retrieval_prefix == "合成目录 > 教程\n| 项目 | 值 |"
    intro = structured("导语。", collection_path=["合成目录"])
    RetrievalPrefixStep().process(intro)
    assert intro.units[0].children[0].retrieval_prefix == "合成目录"
    assert intro.units[0].children[0].body == "导语。"


def test_prefix_without_collection_and_with_truncated_parent_path():
    context = structured("## 安装篇\n\n正文。")
    RetrievalPrefixStep().process(context)
    assert context.units[0].children[0].retrieval_prefix == "教程"
    title = "章节" * 110
    context = structured(f"## {title}\n\n正文。", collection_path=[title])
    RetrievalPrefixStep().process(context)
    assert context.units[0].children[0].retrieval_prefix == "教程"


def test_prefix_survives_budget_splitting_including_table_headers_and_offsets():
    context = structured("## 安装篇\n\n| 项目 | 值 |\n| --- | --- |\n" +
                         "".join(f"| 第{i}项 | 数值{i}GB |\n" for i in range(15)), collection_path=["目录"])
    RetrievalPrefixStep().process(context)
    parent, = BudgetChunker(max_input_units=180).chunk(context.units)
    assert len(parent.children) > 1
    assert any("| 项目 | 值 |" in child.retrieval_prefix for child in parent.children)
    for child in parent.children:
        assert child.retrieval_prefix.startswith("目录 > 教程")
        assert len(evidence_input(parent.title, child.body, child.retrieval_prefix).encode()) <= 180
        assert parent.body[child.locator["parent_char_start"]:child.locator["parent_char_end"]] == child.body


def test_units_enrichment_steps_are_compatible_with_pipeline_stage_validation():
    chunker = BudgetChunker()
    pipeline = PreprocessPipeline([
        ParseStep(ParserRegistry(), image_warning="截图提醒"), StructureStep(SectionedDocumentStrategy(TUTORIAL)),
        CalloutWarningStep(), TimeExpressionStep(), RetrievalPrefixStep(), ChunkStep(chunker),
        BuildDocumentStep(document_schema="tutorial"), ValidateStep(input_validator=chunker.validate),
    ])
    document = pipeline.process(RawDocument(
        "## 安装篇\n\n截至 2025 年仍可用。\n\n![](synthetic.png)".encode(), "text/markdown",
        {"title": "教程", "collection_path": ["目录"], "warnings": ["外部提醒"]},
    ))
    assert document.warnings == ["外部提醒", "截图提醒"]
    assert document.metadata["collection_path"] == ["目录"]
    assert document.contexts[0].metadata["omitted_images"] == 1
    assert document.contexts[0].warnings == ["含时间限定表述‘截至 2025 年’，请结合来源日期判断是否仍适用"]


@pytest.mark.parametrize("media_type,content", [
    ("text/markdown", "## 安装篇\n\n![](synthetic.png)\n\n安装说明。"),
    ("text/x-yuque-markdown", "## 安装篇\n\n![](synthetic.png)\n\n安装说明。"),
    ("text/html", '<h2>安装篇</h2><p><img src="synthetic.png"></p><p>安装说明。</p>'),
])
def test_registered_tutorial_uses_configured_image_warning_for_all_formats(media_type, content):
    document = components.preprocessors().process(
        RawDocument(content.encode(), media_type, {"title": "教程"}), "tutorial", 1,
    )
    assert document.warnings == ["原文含未转写的截图，操作界面以原文链接为准"]
    assert document.contexts[0].title == "安装篇"


@pytest.mark.parametrize("schema", ["product_review", "purchase_guide", "experience_case"])
def test_registered_other_schemas_keep_default_image_warning(schema):
    document = components.preprocessors().process(
        RawDocument("## 合成章节\n\n![](synthetic.png)\n\n合成正文。".encode(), "text/markdown",
                    {"title": "合成文档", "entity_title": "合成机型"}), schema, 1,
    )
    assert document.warnings == ["原文含未提供文字说明的图片，关键参数需人工补录。"]
