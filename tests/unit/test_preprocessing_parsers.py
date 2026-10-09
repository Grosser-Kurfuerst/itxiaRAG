import pytest

from contracts.errors import DomainError
from contracts.types import RawDocument
from ingestion.parsers import HtmlParser, MarkdownParser, ParserRegistry
from ingestion.preprocessing import ParseStep, PreprocessContext


def raw(text, media_type="text/html"):
    return RawDocument(text.encode(), media_type)


def test_markdown_preserves_table_units_lists_and_code_indentation():
    blocks = MarkdownParser().parse(raw(
        "# 经验文档\n\n## 现象\n\n- 黑屏\n- 风扇工作\n\n"
        "| 条件 | 温度 |\n| --- | --- |\n| 室温25℃ | 80℃ |\n\n"
        "```python\n    print('test')\n```\n\n第一行  \n第二行", "text/markdown"
    ))
    assert [b.kind for b in blocks] == ["heading", "heading", "list", "table", "code", "paragraph"]
    assert "室温25℃" in blocks[3].text
    assert blocks[4].text == "```python\n    print('test')\n```"
    assert blocks[5].text == "第一行  \n第二行"
    assert blocks[0].locator == {"line_start": 1, "line_end": 1}


def test_markdown_fence_uses_same_marker_and_keeps_internal_headings():
    blocks = MarkdownParser().parse(raw("~~~bash\n# comment\n```\n~~~", "text/markdown"))
    assert len(blocks) == 1 and blocks[0].kind == "code"
    assert "# comment" in blocks[0].text and "```" in blocks[0].text


def test_wechat_html_selects_body_and_recognizes_strong_columns():
    blocks = HtmlParser().parse(raw(
        '<h1>页头标题</h1><div id="js_content"><section>'
        '<p><strong>【优缺点】</strong></p><p>优点：<b>安静</b><br>缺点：贵</p>'
        '<script>secret()</script><img data-src="https://example.invalid/p.png">'
        '<p><img alt="图片"></p><p><img alt="散热模组"></p>'
        '</section></div><p>广告页尾</p>'
    ))
    assert [(b.kind, b.text) for b in blocks] == [
        ("heading", "【优缺点】"), ("paragraph", "优点：安静\n缺点：贵"),
        ("paragraph", "[图片：未提供文字说明]"), ("paragraph", "[图片：未提供文字说明]"),
        ("paragraph", "[图片：散热模组]"),
    ]
    assert all("页尾" not in b.text and "secret" not in b.text for b in blocks)


def test_html_preserves_code_whitespace_and_table_header_cells():
    blocks = HtmlParser().parse(raw(
        '<body><h1>测试</h1><table><tr><th>条件</th><th>结果</th></tr>'
        '<tr><td>室温25℃</td><td>80℃</td></tr></table><pre>    a\n    b</pre></body>'
    ))
    assert [b.text for b in blocks] == ["测试", "| 条件 | 结果 |", "| 室温25℃ | 80℃ |", "    a\n    b"]


def test_bom_charset_and_explicit_parser_registration():
    registry = ParserRegistry()
    assert registry.parse(RawDocument(b"\xef\xbb\xbftext", "text/markdown; charset=utf-8"))[0].text == "text"
    registry.register("text/custom", MarkdownParser())
    assert registry.parse(raw("自定义", "text/custom"))[0].text == "自定义"
    with pytest.raises(ValueError, match="已注册"):
        registry.register("text/custom", MarkdownParser())
    with pytest.raises(DomainError, match="格式"):
        registry.parse(raw("正文", "application/pdf"))
    with pytest.raises(DomainError, match="UTF-8"):
        registry.parse(RawDocument(b"\xff", "text/plain"))


def test_wechat_nested_style_spans_keep_column_boundaries_and_text_order():
    blocks = HtmlParser().parse(raw(
        '<div id="js_content"><section><span><p><span style="color:red">'
        '<strong>【优缺点】</strong></span></p><p>优点：安静</p>'
        '<p><span>【购买建议】</span></p><p>不建议购买。</p></span></section></div>'
    ))
    assert [(b.kind, b.text) for b in blocks] == [
        ("heading", "【优缺点】"), ("paragraph", "优点：安静"),
        ("heading", "【购买建议】"), ("paragraph", "不建议购买。"),
    ]


@pytest.mark.parametrize("alt,description", [
    ("散热模组", "散热模组"), ("", "未提供文字说明"),
    ("图片", "未提供文字说明"), (" 图片 ", "未提供文字说明"),
])
def test_markdown_image_blocks_share_html_placeholders_and_keep_source_in_metadata(alt, description):
    source = "https://example.invalid/image(1).png"
    blocks = MarkdownParser().parse(raw(f'前文\n![{alt}]({source} "图示")\n后文', "text/markdown"))
    assert [(block.kind, block.text) for block in blocks] == [
        ("paragraph", "前文"), ("image", f"[图片：{description}]"), ("paragraph", "后文"),
    ]
    assert blocks[1].metadata == {"src": source}
    assert blocks[1].locator == {"line_start": 2, "line_end": 2}
    assert [block.ordinal for block in blocks] == [1, 2, 3]


def test_markdown_inline_images_are_replaced_in_paragraphs_headings_lists_tables_and_quotes():
    blocks = MarkdownParser().parse(raw(
        "## 图 ![示意](<https://example.invalid/h.png>)\n"
        "前文 ![](https://example.invalid/p.png) 后文\n"
        "- ![图片](https://example.invalid/l.png)\n"
        "| ![表](https://example.invalid/t.png) |\n"
        "> ![引用](https://example.invalid/q.png)", "text/markdown",
    ))
    assert [(block.kind, block.text) for block in blocks] == [
        ("heading", "图 [图片：示意]"), ("paragraph", "前文 [图片：未提供文字说明] 后文"),
        ("list", "- [图片：未提供文字说明]"), ("table", "| [图片：表] |"),
        ("quote", "[图片：引用]"),
    ]


@pytest.mark.parametrize("content", ["![图片](image.png)", "正文 ![](image.png)"])
def test_markdown_missing_image_description_uses_existing_parse_step_warning(content):
    context = ParseStep(MarkdownParser()).process(PreprocessContext(raw(content, "text/markdown")))
    assert context.warnings == ["原文含未提供文字说明的图片，关键参数需人工补录。"]


def test_markdown_contiguous_quote_lines_form_one_block_with_original_line_range():
    blocks = MarkdownParser().parse(raw("前文\n> 第一行\n>\n  > 第二行\n后文", "text/markdown"))
    assert [(block.kind, block.text) for block in blocks] == [
        ("paragraph", "前文"), ("quote", "第一行\n\n第二行"), ("paragraph", "后文"),
    ]
    assert blocks[1].locator == {"line_start": 2, "line_end": 4}


@pytest.mark.parametrize("marker,level,label", [
    ("NOTE", "note", "【提示】"), ("TIP", "note", "【提示】"),
    ("IMPORTANT", "note", "【注意】"), ("WARNING", "warning", "【警告】"),
    ("CAUTION", "caution", "【警告】"),
])
def test_markdown_github_callouts_preserve_body_and_record_level(marker, level, label):
    blocks = MarkdownParser().parse(raw(f"> [!{marker}]\n> 先备份。\n> 再处理。", "text/markdown"))
    assert len(blocks) == 1
    assert (blocks[0].kind, blocks[0].text, blocks[0].metadata) == (
        "callout", label + "\n先备份。\n再处理。", {"level": level},
    )
    assert blocks[0].locator == {"line_start": 1, "line_end": 3}


@pytest.mark.parametrize("first_line", ["> 正文", ">"])
def test_markdown_only_recognizes_callout_marker_on_first_quote_line(first_line):
    block = MarkdownParser().parse(raw(first_line + "\n> [!WARNING]", "text/markdown"))[0]
    assert block.kind == "quote" and block.metadata == {}
    assert block.text.endswith("[!WARNING]")


def test_markdown_empty_headings_are_ignored_without_losing_neighboring_line_positions():
    blocks = MarkdownParser().parse(raw("前文\n#\n## \n###   \n后文", "text/markdown"))
    assert [(block.kind, block.text) for block in blocks] == [("paragraph", "前文"), ("paragraph", "后文")]
    assert [block.locator for block in blocks] == [
        {"line_start": 1, "line_end": 1}, {"line_start": 5, "line_end": 5},
    ]


def test_markdown_heading_links_keep_text_while_body_links_remain():
    blocks = MarkdownParser().parse(raw(
        "## 工具 > [Parsec](https://example.invalid/parsec)\n**[官网](https://example.invalid/)**\n见 [文档](https://example.invalid/doc)",
        "text/markdown",
    ))
    assert [(block.kind, block.text) for block in blocks] == [
        ("heading", "工具 > Parsec"), ("heading", "官网"), ("paragraph", "见 [文档](https://example.invalid/doc)"),
    ]


def test_markdown_default_pseudo_headings_remain_level_two_for_long_or_punctuated_labels():
    labels = ["结论，仍然是标题。", "长" * 31]
    blocks = MarkdownParser().parse(raw("### 章节\n" + "\n".join(f"**{label}**" for label in labels), "text/markdown"))
    assert [(block.kind, block.text, block.level) for block in blocks] == [
        ("heading", "章节", 3),
    ] + [("heading", label, 2) for label in labels]


def test_markdown_nested_labels_follow_last_real_heading_without_increasing_each_other():
    parser = MarkdownParser(pseudo_heading="nested_label")
    blocks = parser.parse(raw(
        "**开场**\n## 章节\n**标签一**\n**标签二**\n###### 深层\n**标签三**", "text/markdown",
    ))
    assert [block.level for block in blocks] == [2, 2, 3, 3, 6, 6]
    assert parser.parse(raw("**新的文档**", "text/markdown"))[0].level == 2


@pytest.mark.parametrize("label", ["长" * 31, *(f"句内{mark}标点" for mark in "，。；！？,;!?")])
def test_markdown_nested_labels_keep_long_or_punctuated_bold_lines_as_paragraphs(label):
    block = MarkdownParser(pseudo_heading="nested_label").parse(raw(f"**{label}**", "text/markdown"))[0]
    assert (block.kind, block.text, block.level) == ("paragraph", f"**{label}**", None)


def test_markdown_nested_label_accepts_thirty_characters():
    block = MarkdownParser(pseudo_heading="nested_label").parse(raw("**" + "字" * 30 + "**", "text/markdown"))[0]
    assert block.kind == "heading" and block.level == 2


def test_markdown_rejects_unknown_pseudo_heading_configuration():
    with pytest.raises(ValueError, match="pseudo_heading"):
        MarkdownParser(pseudo_heading="unknown")


def test_markdown_enhancements_do_not_rewrite_fenced_code():
    content = "```markdown\n#\n**标签**\n![图片](image.png)\n> [!WARNING]\n```"
    blocks = MarkdownParser(pseudo_heading="nested_label").parse(raw(content, "text/markdown"))
    assert len(blocks) == 1 and blocks[0].kind == "code" and blocks[0].text == content


def test_markdown_quote_fence_does_not_protect_following_paragraph_images():
    blocks = MarkdownParser().parse(raw(
        "> ```markdown\n> ![示例](demo.png)\n正文 ![说明](after.png)", "text/markdown",
    ))
    assert [(block.kind, block.text) for block in blocks] == [
        ("quote", "```markdown\n![示例](demo.png)"),
        ("paragraph", "正文 [图片：说明]"),
    ]
