from dataclasses import replace

import pytest

from contracts.types import RawDocument
from ingestion.chunking import BudgetChunker
from ingestion.parsers import HtmlParser, MarkdownParser
from ingestion.sections import SectionedDocumentStrategy, TUTORIAL, build_tree
from ingestion.strategies import _key


def build(text, *, profile=None, title="合成教程"):
    raw = RawDocument(text.encode(), "text/markdown", {"title": title})
    blocks = MarkdownParser(pseudo_heading="nested_label").parse(raw)
    return SectionedDocumentStrategy(profile or replace(TUTORIAL, min_parent_chars=0)).build(blocks, raw)


@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_top_level_is_adaptive_and_skipped_levels_are_nested(level):
    parents = build(f"{'#' * level} 安装篇\n\n说明。\n\n{'#' * (level + 2)} 开始安装\n\n选择分区。\n\n"
                    f"{'#' * level} 设置篇\n\n调整设置。")
    assert [parent.title for parent in parents] == ["安装篇", "设置篇"]
    assert "开始安装" in parents[0].body and "选择分区" in parents[0].body
    assert parents[0].metadata["content_type"] == "tutorial"


def test_tree_keeps_document_and_section_introductions():
    raw = RawDocument("文档导语\n\n## 安装篇\n\n章节导语\n\n#### 第一步\n\n操作说明".encode(), "text/markdown")
    root = build_tree(MarkdownParser().parse(raw))
    assert [block.text for block in root.blocks] == ["文档导语"]
    node, = root.children
    assert node.level == 2 and [block.text for block in node.blocks] == ["章节导语"]
    assert node.children[0].level == 4 and node.size() == len("章节导语操作说明")


def test_wrapper_headings_descend_repeatedly_and_preserve_introductions():
    text = "开头。\n\n# 重复文档标题\n\n包裹导语。\n\n## 另一个包裹标题\n\n### 安装篇\n\n" + "安装说明。" * 40
    parents = build(text, profile=TUTORIAL)
    parent, = parents
    assert parent.title == "安装篇"
    assert parent.key == _key("context", "安装篇")
    assert all(text in parent.body for text in ["开头。", "包裹导语。", "安装说明。"])
    assert "重复文档标题" not in parent.body and "另一个包裹标题" not in parent.body


def test_long_sections_drill_down_and_keep_introduction_as_parent():
    text = ("文档导语。\n\n## 安装篇\n\n章节导语。\n\n#### 进入装机盘\n\n" + "开机操作。" * 10
            + "\n\n#### 开始安装\n\n" + "安装操作。" * 10 + "\n\n## 设置篇\n\n设置操作。")
    parents = build(text, profile=replace(TUTORIAL, max_parent_chars=60, min_parent_chars=0))
    assert [parent.title for parent in parents] == [
        "合成教程", "安装篇", "安装篇 > 进入装机盘", "安装篇 > 开始安装", "设置篇",
    ]
    assert parents[0].body == "文档导语。"
    assert parents[1].body == "安装篇\n\n章节导语。"
    assert parents[2].locator == {"block_start": 4, "block_end": 5, "line_start": 7, "line_end": 9}
    assert [parent.metadata["section_path"] for parent in parents][2] == ["安装篇", "进入装机盘"]


def test_long_leaf_is_one_parent_and_budget_chunker_splits_its_children():
    parents = build("## 安装篇\n\n" + "很长的安装步骤。" * 40,
                    profile=replace(TUTORIAL, max_parent_chars=40, min_parent_chars=0))
    assert len(parents) == 1
    chunked, = BudgetChunker(max_input_units=120).chunk(parents)
    assert len(chunked.children) > 1
    assert all(not child.atomic and "-part-" in child.key for child in chunked.children)
    for child in chunked.children:
        assert chunked.body[child.locator["parent_char_start"]:child.locator["parent_char_end"]] == child.body


@pytest.mark.parametrize("text,receiver", [
    ("## 短篇\n\n短。\n\n## 长篇\n\n" + "长内容。" * 10, "长篇"),
    ("## 长篇\n\n" + "长内容。" * 10 + "\n\n## 短篇\n\n短。", "长篇"),
])
def test_short_parent_merge_preserves_receiver_title_key_and_source_order(text, receiver):
    parent, = build(text, profile=replace(TUTORIAL, min_parent_chars=15))
    assert parent.title == receiver and parent.key == _key("context", receiver)
    first, second = ("短篇", "长篇") if text.startswith("## 短篇") else ("长篇", "短篇")
    assert parent.body.index(first) < parent.body.index(second)
    assert (parent.locator["block_start"], parent.locator["block_end"]) == (1, 4)


def test_short_parents_do_not_merge_across_different_ancestors():
    text = ("## 第一篇\n\n### 短节\n\n短。\n\n### 长节\n\n" + "长内容。" * 10
            + "\n\n## 第二篇\n\n### 短节\n\n短。\n\n### 长节\n\n" + "长内容。" * 10)
    parents = build(text, profile=replace(TUTORIAL, max_parent_chars=20, min_parent_chars=15))
    assert [parent.title for parent in parents] == ["第一篇 > 长节", "第二篇 > 长节"]
    assert "第二篇" not in parents[0].body and "第一篇" not in parents[1].body
    single, = build("## 唯一节\n\n短。", profile=TUTORIAL)
    assert single.title == "唯一节"


def test_untitled_document_uses_metadata_title_and_empty_input_has_no_parents():
    parent, = build("段落一。\n\n段落二。")
    assert parent.title == "合成教程" and parent.body == "段落一。\n\n段落二。"
    assert parent.key == _key("context", "合成教程")
    assert build("") == []


@pytest.mark.parametrize("text,joined", [
    ("所需材料：\n\n备份盘与安装盘。\n\n其他内容。", ["所需材料：", "备份盘与安装盘。"]),
    ("先备份文件；\n\n再制作装机盘。\n\n其他内容。", ["先备份文件；", "再制作装机盘。"]),
    ("- 安装盘\n\n- 备份盘\n\n其他内容。", ["- 安装盘", "- 备份盘"]),
    ("1、备份文件。\n\n2、制作装机盘。\n\n其他内容。", ["1、备份文件。", "2、制作装机盘。"]),
    ("删除分区。\n\n> [!WARNING]\n> 先确认备份。\n\n其他内容。", ["删除分区。", "先确认备份。"]),
])
def test_child_link_rules_keep_connected_blocks_even_over_target(text, joined):
    parent, = build(text, profile=replace(TUTORIAL, chunk_target_chars=8, chunk_min_chars=0))
    assert all(part in parent.children[0].body for part in joined)
    assert "其他内容。" not in parent.children[0].body


def test_every_heading_opens_a_child_and_stays_with_its_following_content():
    parent, = build("## 安装篇\n\n导语。\n\n### 这个小节标题超过三十个字符因此不能依赖评测策略的短栏目识别判断\n\n"
                    "第一步。\n\n#### 子步骤\n\n第二步。",
                    profile=replace(TUTORIAL, chunk_target_chars=8, chunk_min_chars=0))
    assert len(parent.children) == 3
    assert "第一步。" in parent.children[1].body
    assert parent.children[2].body == "子步骤\n\n第二步。"


def test_consecutive_headings_stay_with_following_body_using_tutorial_defaults():
    body = "准备安装盘并备份重要文件。" * 20
    parents = build("## 准备篇\n\n### 准备材料\n\n" + body
                    + "\n\n## 安装篇\n\n" + "按照说明完成安装。" * 20, profile=TUTORIAL)
    assert [parent.title for parent in parents] == ["准备篇", "安装篇"]
    child, = parents[0].children
    assert child.body == "准备篇\n\n准备材料\n\n" + body
    assert child.key == _key("evidence", "准备材料") + "-1"
    assert child.metadata["section"] == "准备材料"
    assert child.locator == {"block_start": 1, "block_end": 3, "line_start": 1, "line_end": 5}


def test_short_children_merge_into_previous_child():
    parent, = build("## 安装篇\n\n" + "安装说明。" * 10 + "\n\n### 附注\n\n短。",
                    profile=replace(TUTORIAL, min_parent_chars=0, chunk_target_chars=30, chunk_min_chars=10))
    child, = parent.children
    assert "附注\n\n短。" in child.body
    assert child.key == _key("evidence", "安装篇") + "-1"


def test_keys_are_stable_across_edits_to_unrelated_sections_and_duplicate_paths_are_unique():
    profile = replace(TUTORIAL, min_parent_chars=0, chunk_target_chars=15, chunk_min_chars=0)
    original = build("## 安装篇\n\n### 甲节\n\n原文。\n\n### 乙节\n\n保留正文。\n\n## 安装篇\n\n另一篇。", profile=profile)
    edited = build("## 安装篇\n\n### 甲节\n\n" + "新增很多正文。" * 10
                   + "\n\n### 乙节\n\n保留正文。\n\n## 安装篇\n\n另一篇。", profile=profile)
    assert [p.key for p in original] == [p.key for p in edited]
    assert len({p.key for p in original}) == 2
    assert original[1].key == original[0].key + "-2"
    keys = lambda parents: [c.key for c in parents[0].children if c.metadata["section"] == "乙节"]
    assert keys(original) == keys(edited)
    duplicated, = build("## 安装篇\n\n### 步骤\n\n甲。\n\n### 步骤\n\n乙。", profile=profile)
    assert len({c.key for c in duplicated.children}) == len(duplicated.children)


def test_titles_over_200_characters_keep_both_ends_and_hash_full_path():
    title = "安装篇" + "很长的路径" * 50 + "开始安装"
    parent, = build(f"## {title}\n\n说明。")
    assert len(parent.title) == 200 and "…" in parent.title
    assert parent.title.startswith("安装篇") and parent.title.endswith("开始安装")
    assert parent.key == _key("context", title)


def test_omitted_images_are_counted_in_their_parent_including_range_edges():
    parents = build("![](before.png)\n\n## 安装篇\n\n![](start.png)\n\n说明。\n\n"
                    "![分区界面](partition.png)\n\n![](end.png)\n\n## 设置篇\n\n![](settings.png)\n\n设置。")
    assert [parent.metadata["omitted_images"] for parent in parents] == [3, 1]
    assert "[图片：分区界面]" in parents[0].body
    assert all("未提供文字说明" not in parent.body for parent in parents)
    assert (parents[0].locator["block_start"], parents[0].locator["block_end"]) == (1, 6)
    assert (parents[1].locator["line_start"], parents[1].locator["line_end"]) == (13, 17)
    assert build("![](only.png)") == []


def test_html_image_only_paragraphs_and_multiple_images_are_omitted_and_counted():
    raw = RawDocument(b'<h2>Install</h2><p><img><br><img></p><p>Keep text.</p>', "text/html", {"title": "Doc"})
    parent, = SectionedDocumentStrategy(TUTORIAL).build(HtmlParser().parse(raw), raw)
    assert parent.metadata["omitted_images"] == 2 and "未提供文字说明" not in parent.body


def test_markdown_inline_images_are_removed_from_paragraphs_and_lists_with_original_locators():
    raw = RawDocument(
        ("## 安装篇\n\n![](only.png)\n\n点击下一步  ![](shot.png)   确认选项。\n"
         "继续操作 ![](extra.png)\n\n- 保存设置 ![图片](save.png)\n\n"
         "![分区界面](partition.png)\n\n## 设置篇\n\n调整选项 ![](settings.png)").encode(),
        "text/markdown", {"title": "合成教程"},
    )
    blocks = MarkdownParser().parse(raw)
    original_texts = [block.text for block in blocks]
    parents = SectionedDocumentStrategy(replace(
        TUTORIAL, min_parent_chars=0, chunk_target_chars=0, chunk_min_chars=0,
    )).build(blocks, raw)
    assert [parent.metadata["omitted_images"] for parent in parents] == [4, 1]
    assert parents[0].body == "安装篇\n\n点击下一步 确认选项。\n继续操作\n\n- 保存设置\n\n[图片：分区界面]"
    assert parents[1].body == "设置篇\n\n调整选项"
    assert parents[0].locator == {"block_start": 1, "block_end": 5, "line_start": 1, "line_end": 10}
    assert parents[0].children[0].locator == {
        "block_start": 1, "block_end": 3, "line_start": 1, "line_end": 6,
    }
    assert parents[0].children[1].locator == {
        "block_start": 4, "block_end": 4, "line_start": 8, "line_end": 8,
    }
    assert all("未提供文字说明" not in child.body for parent in parents for child in parent.children)
    assert [block.text for block in blocks] == original_texts


def test_html_mixed_images_are_removed_and_counted_per_parent():
    raw = RawDocument(
        ('<h2>安装篇</h2><p><img></p>'
         '<p>点击下一步 <img src="shot.png">  确认选项。<br>继续操作<img></p>'
         '<ul><li>保存设置 <img alt="图片"></li></ul><p><img alt="分区界面"></p>'
         '<h2>设置篇</h2><p>调整选项<img></p>').encode(),
        "text/html", {"title": "合成教程"},
    )
    parents = SectionedDocumentStrategy(replace(
        TUTORIAL, min_parent_chars=0, chunk_target_chars=0, chunk_min_chars=0,
    )).build(HtmlParser().parse(raw), raw)
    assert [parent.metadata["omitted_images"] for parent in parents] == [4, 1]
    assert parents[0].body == "安装篇\n\n点击下一步 确认选项。\n继续操作\n\n保存设置\n\n[图片：分区界面]"
    assert parents[1].body == "设置篇\n\n调整选项"
    assert parents[0].locator == {"block_start": 1, "block_end": 5}
    assert parents[1].locator == {"block_start": 6, "block_end": 7}
    assert parents[0].children[0].locator == {"block_start": 1, "block_end": 3}
    assert parents[0].children[1].locator == {"block_start": 4, "block_end": 4}
    assert all("未提供文字说明" not in child.body for parent in parents for child in parent.children)


@pytest.mark.parametrize("marker,label", [("[!TIP]", "【提示】\n"), ("", "")])
def test_image_removal_preserves_other_lines_in_callouts_and_quotes(marker, label):
    text = "## 安装篇\n\n" + (f"> {marker}\n" if marker else "") + (
        ">     def example():\n"
        ">         value = 1  +  2\n"
        ">   - 保留列表缩进  \n"
        ">   点击下一步  ![](shot.png)   确认选项。\n"
        ">     return 1  "
    )
    parent, = build(text)
    expected = "安装篇\n\n" + label + (
        "    def example():\n"
        "        value = 1  +  2\n"
        "  - 保留列表缩进  \n"
        "点击下一步 确认选项。\n"
        "    return 1  "
    )
    assert parent.body == expected
    child, = parent.children
    assert child.body == expected
    assert parent.metadata["omitted_images"] == 1


def test_images_before_drilled_child_belong_to_that_chapter_instead_of_previous_chapter():
    parents = build("## 准备篇\n\n准备说明。\n\n## 安装篇\n\n![](intro.png)\n\n### 选择分区\n\n"
                    + "分区说明。" * 10 + "\n\n### 完成安装\n\n" + "安装说明。" * 10,
                    profile=replace(TUTORIAL, max_parent_chars=20, min_parent_chars=0))
    assert [parent.title for parent in parents] == ["准备篇", "安装篇 > 选择分区", "安装篇 > 完成安装"]
    assert [parent.metadata["omitted_images"] for parent in parents] == [0, 1, 0]
    assert parents[0].locator["block_end"] == 2 and parents[1].locator["block_start"] == 3


def test_intro_and_subsection_named_body_have_distinct_child_keys():
    parent, = build("导语。\n\n## 正文\n\n正文说明。", profile=replace(TUTORIAL, chunk_min_chars=0))
    assert len(parent.children) == 2
    assert len({child.key for child in parent.children}) == len(parent.children)


def test_table_and_code_are_merged_whole_and_can_be_split_by_budget():
    text = "## 安装篇\n\n| 项目 | 值 |\n| --- | --- |\n" + "".join(f"| 第{i}项 | 数值{i}GB |\n" for i in range(10))
    text += "\n```sh\n" + "echo synthetic\n" * 20 + "```"
    parent, = build(text, profile=replace(TUTORIAL, chunk_target_chars=30, chunk_min_chars=0))
    assert any("```sh" in child.body and child.body.endswith("```") for child in parent.children)
    assert all(not child.atomic for child in parent.children)
    chunked, = BudgetChunker(max_input_units=180).chunk([parent])
    assert any("| 项目 | 值 |" in child.retrieval_prefix for child in chunked.children)
    assert len(chunked.children) > len(parent.children)
