import pytest

from config import components
from contracts.errors import DomainError
from contracts.types import RawDocument
from ingestion.parsers import MarkdownParser
from ingestion.yuque_markdown import YuqueMarkdownParser, normalize_yuque


@pytest.mark.parametrize("tag", ["font", "span", "u", "sup", "sub", "mark", "strong", "em"])
def test_yuque_removes_only_whitelisted_style_tags_and_preserves_their_text(tag):
    assert normalize_yuque(f'<{tag} style="color:red">文字</{tag}>\n') == "文字\n"


def test_yuque_preserves_unknown_angle_brackets_and_placeholder_names():
    content = "<你的用户名> <你的Windows用户名> <font-color>文字</font-color> <custom>文字</custom>\n"
    assert normalize_yuque(content) == content
    assert normalize_yuque("<FONT><span>嵌套</span></FONT>") == "嵌套"


@pytest.mark.parametrize("tag", ["<br>", "<br/>", "<br />", "<BR/>"])
def test_yuque_table_breaks_become_semicolons_without_splitting_rows(tag):
    content = f"| 项目 | 条件{tag}结果 |\n普通行{tag}保留\n"
    assert normalize_yuque(content) == f"| 项目 | 条件；结果 |\n普通行{tag}保留\n"


@pytest.mark.parametrize("kind,marker", [
    ("warning", "WARNING"), ("danger", "CAUTION"), ("tips", "NOTE"),
    ("info", "NOTE"), ("success", "NOTE"), ("color1", "NOTE"), ("color12", "NOTE"),
])
def test_yuque_callout_dialects_become_github_markers_and_keep_blank_body_lines(kind, marker):
    content = f":::{kind}\n<font>先备份。</font>\n\n再处理。\n:::\n正文\n"
    assert normalize_yuque(content) == f"> [!{marker}]\n> 先备份。\n> \n> 再处理。\n\n正文\n"


def test_yuque_unknown_callout_type_is_preserved():
    content = ":::unknown\n正文\n:::\n"
    assert normalize_yuque(content) == content


def test_yuque_single_line_details_use_html_text_and_discard_images():
    content = (
        '<details open><summary><strong>折叠标题</strong></summary>'
        '<p>第一段<br/>下一行<img src="hidden.png" alt="丢弃说明"></p>'
        '<p>第二段 &amp; 结果</p></details>\n'
    )
    assert normalize_yuque(content) == "**折叠标题**：第一段 下一行 第二段 & 结果\n"


def test_yuque_multiline_details_are_not_collapsed_or_removed():
    content = "<details>\n<summary>标题</summary>\n正文\n</details>\n"
    assert normalize_yuque(content) == content


@pytest.mark.parametrize("image,expected", [
    ('<img src="https://cdn.nlark.com/synthetic.png" alt="示意" />', '![示意](https://cdn.nlark.com/synthetic.png)'),
    ("<img src='image.png'>", "![](image.png)"),
    ('<IMG alt="图片" src="image.png">', '![图片](image.png)'),
])
def test_yuque_standalone_html_images_become_markdown_images(image, expected):
    assert normalize_yuque(image + "\n") == expected + "\n"


def test_yuque_inline_html_images_remain_outside_standalone_image_rule():
    content = '正文 <img src="image.png" alt="图">\n'
    assert normalize_yuque(content) == content


@pytest.mark.parametrize("content", ["#### ", "****", "** **", "<font><span> </span></font>", ">", "> "])
def test_yuque_empty_structures_become_blank_lines(content):
    assert normalize_yuque(content + "\n正文\n") == "\n正文\n"


@pytest.mark.parametrize("content,expected", [
    ("**数据****，所以…**", "**数据，所以…**"),
    ("“**USB Boot（****从USB启动****）**”", "“**USB Boot（从USB启动）**”"),
    ("正文**<span></span>**后文", "正文后文"),
])
def test_yuque_removes_inline_empty_bold_after_styles_but_preserves_fenced_code(content, expected):
    assert normalize_yuque(content + "\n") == expected + "\n"
    code = f"```markdown\n{content}\n```\n"
    assert normalize_yuque(code) == code


def test_yuque_anchor_links_keep_text_and_other_links_remain_unchanged():
    content = "[本节](#anchor) [语雀](https://www.yuque.com/synthetic/doc) [官网](https://example.invalid/)\n"
    assert normalize_yuque(content) == "本节 [语雀](https://www.yuque.com/synthetic/doc) [官网](https://example.invalid/)\n"


def test_yuque_strikethrough_removes_deleted_text_only():
    assert normalize_yuque("有效 ~~废弃~~ ~~另一条~~正文\n") == "有效  正文\n"


@pytest.mark.parametrize("content,expected", [
    ("> ~~旧说明，~~`~~old.example~~`~~已失效~~", ""),
    ("改用 ~~旧~~`~~old~~` `new` 接口", "改用  `new` 接口"),
    ("## ~~作废标题~~", ""),
])
def test_yuque_strikethrough_drops_deleted_inline_code_and_resulting_empty_structures(content, expected):
    assert normalize_yuque(content + "\n正文\n") == expected + "\n正文\n"


@pytest.mark.parametrize("opening,closing", [("```markdown", "```"), ("~~~~markdown", "~~~~~")])
def test_yuque_fenced_code_preserves_all_dialects_and_requires_matching_closer(opening, closing):
    content = (
        f"{opening}\n<font>原文</font>\n| A<br/>B |\n:::warning\n:::\n"
        "<details><summary>S</summary>正文</details>\n<img src='image.png'>\n"
        "****\n[锚点](#a) ~~保留~~ <你的用户名>\n~~~\n``\n"
        f"{closing}\n<font>后文</font>\n"
    )
    assert normalize_yuque(content) == content.replace("<font>后文</font>", "后文")


def test_yuque_callout_normalizes_images_and_tables_and_preserves_code_contents():
    content = (
        ':::warning\n<img src="image.png">\n| A<br/>B |\n'
        '```markdown\n<font>保留</font>\n:::danger\n```\n:::\n'
    )
    assert normalize_yuque(content) == (
        '> [!WARNING]\n> ![](image.png)\n> | A；B |\n'
        '> ```markdown\n> <font>保留</font>\n> :::danger\n> ```\n\n'
    )


@pytest.mark.parametrize("opening,closing", [("```markdown", "```"), ("~~~~markdown", "~~~~~")])
def test_yuque_parser_preserves_fenced_code_inside_callouts(opening, closing):
    code = (
        f"{opening}\n![示例](demo.png)\n    正文 ![](inline.png)\n"
        "<font>保留</font>\n**标签**\n#\n****\n:::danger\n~~~\n``\n"
        f"{closing}"
    )
    content = f":::tips\n前文 ![说明](before.png)\n{code}\n后文 ![说明](after.png)\n:::\n正文\n"
    blocks = YuqueMarkdownParser().parse(RawDocument(content.encode(), "text/x-yuque-markdown"))
    assert [(block.kind, block.text, block.metadata) for block in blocks] == [
        ("callout", f"【提示】\n前文 [图片：说明]\n{code}\n后文 [图片：说明]", {"level": "note"}),
        ("paragraph", "正文", {}),
    ]
    assert blocks[0].locator == {"line_start": 1, "line_end": 14}


@pytest.mark.parametrize("kind,level,label", [
    ("tips", "note", "【提示】"), ("warning", "warning", "【警告】"),
    ("danger", "caution", "【警告】"),
])
def test_yuque_parser_maps_callout_labels_and_levels(kind, level, label):
    content = f":::{kind}\n先备份。\n:::\n"
    blocks = YuqueMarkdownParser().parse(RawDocument(content.encode(), "text/x-yuque-markdown"))
    assert len(blocks) == 1
    assert (blocks[0].kind, blocks[0].text, blocks[0].metadata) == (
        "callout", label + "\n先备份。", {"level": level},
    )


def test_yuque_parser_preserves_original_line_ranges_after_normalization():
    content = (
        '# 文档\n#### \n## 案例\n<font>正文</font>\n:::warning\n先备份。\n:::\n'
        '<img src="image.png">\n<details><summary>补充</summary>说明</details>\n'
        '| 项目 | 结果 |\n| --- | --- |\n| 检查 | 条件<br/>结果 |\n'
    )
    normalized = normalize_yuque(content)
    assert len(normalized.splitlines()) == len(content.splitlines())
    blocks = YuqueMarkdownParser().parse(RawDocument(content.encode(), "text/x-yuque-markdown"))
    assert [(block.kind, block.locator) for block in blocks] == [
        ("heading", {"line_start": 1, "line_end": 1}),
        ("heading", {"line_start": 3, "line_end": 3}),
        ("paragraph", {"line_start": 4, "line_end": 4}),
        ("callout", {"line_start": 5, "line_end": 6}),
        ("image", {"line_start": 8, "line_end": 8}),
        ("paragraph", {"line_start": 9, "line_end": 9}),
        ("table", {"line_start": 10, "line_end": 12}),
    ]
    assert blocks[-1].text.endswith("| 检查 | 条件；结果 |")


@pytest.mark.parametrize("content", ["正文\n****", "****", "正文\n~~删除~~"])
def test_yuque_preserves_line_count_when_final_line_without_newline_is_removed(content):
    assert len(normalize_yuque(content).splitlines()) == len(content.splitlines())


def test_yuque_parser_decodes_bom_and_crlf_uses_nested_labels_and_accepts_injected_inner():
    raw = RawDocument(b"\xef\xbb\xbf" + "### 章节\r\n**标签**\r\n<font>正文</font>".encode(),
                      "text/x-yuque-markdown; charset=utf-8", {"title": "合成文档"})
    blocks = YuqueMarkdownParser().parse(raw)
    assert [(block.text, block.level) for block in blocks] == [("章节", 3), ("标签", 4), ("正文", None)]
    assert YuqueMarkdownParser(inner=MarkdownParser()).parse(raw)[1].level == 2
    assert raw.content.startswith(b"\xef\xbb\xbf") and raw.metadata == {"title": "合成文档"}


def test_yuque_parser_rejects_invalid_utf8_with_existing_domain_error():
    with pytest.raises(DomainError, match="UTF-8"):
        YuqueMarkdownParser().parse(RawDocument(b"\xff", "text/x-yuque-markdown"))


@pytest.mark.parametrize("schema", ["product_review", "purchase_guide", "experience_case"])
def test_yuque_media_type_is_registered_for_all_existing_schemas(schema):
    content = (
        '# 合成样本\n\n## 电池案例\n\n<font>续航不足，检查电池。</font>\n\n'
        ':::warning\n拆机前断开电源。\n:::\n\n![图片](https://cdn.nlark.com/synthetic.png)\n'
    )
    raw = RawDocument(content.encode(), "text/x-yuque-markdown; charset=utf-8",
                      {"title": "合成样本", "entity_title": "Laptop A"})
    document = components.preprocessors().process(raw, schema, 1)
    assert document.document_schema == schema and document.schema_version == 1
    assert document.warnings == ["原文含未提供文字说明的图片，关键参数需人工补录。"]
    body = "\n".join(context.body for context in document.contexts)
    assert "续航不足，检查电池。" in body and "【警告】\n拆机前断开电源。" in body
    assert all(marker not in body for marker in ["<font", ":::", "cdn.nlark.com"])
