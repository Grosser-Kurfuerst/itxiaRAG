import pytest

from contracts.errors import DomainError
from contracts.types import RawDocument
from ingestion.parsers import HtmlParser, MarkdownParser, ParserRegistry


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
        '</section></div><p>广告页尾</p>'
    ))
    assert [(b.kind, b.text) for b in blocks] == [
        ("heading", "【优缺点】"), ("paragraph", "优点：安静\n缺点：贵"),
        ("paragraph", "[图片：未提供文字说明]"),
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
