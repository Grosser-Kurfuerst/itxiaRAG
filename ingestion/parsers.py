"""HTML/Markdown 到统一内容块的格式适配器；不抓取 URL 或图片。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from contracts.errors import DomainError
from contracts.types import RawDocument
from ingestion.preprocessing import ContentBlock, Parser


def _decode(raw: RawDocument) -> str:
    try:
        return raw.content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        raise DomainError("INVALID_RAW_DOCUMENT", "原文必须是 UTF-8 文本") from None


def _image_text(alt: str) -> str:
    # 编辑器默认 alt 为“图片”，不构成文字说明。
    alt = alt.strip()
    return f"[图片：{alt}]" if alt and alt != "图片" else "[图片：未提供文字说明]"


class MarkdownParser:
    """保留 Markdown 块结构，图片与提示块转为可检索的文字。"""

    _heading = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
    _empty_heading = re.compile(r"^ {0,3}#{1,6}\s*$")
    _list = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
    _fence = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
    _image = re.compile(
        r'!\[([^\]\n]*)\]\(\s*(<[^>\n]*>|(?:[^()\s]|\([^()\s]*\))*)'
        r'''\s*(?:"[^"\n]*"|'[^'\n]*')?\s*\)'''
    )
    _quote = re.compile(r"^ {0,3}> ?(.*)$")
    _link = re.compile(r"(?<!!)\[([^\]\n]*)\]\([^)\n]*\)")
    _callouts = {
        "[!NOTE]": ("note", "【提示】"),
        "[!TIP]": ("note", "【提示】"),
        "[!IMPORTANT]": ("note", "【注意】"),
        "[!WARNING]": ("warning", "【警告】"),
        "[!CAUTION]": ("caution", "【警告】"),
    }

    def __init__(self, pseudo_heading: str = "level2"):
        if pseudo_heading not in {"level2", "nested_label"}:
            raise ValueError("pseudo_heading 必须为 level2 或 nested_label")
        self.pseudo_heading = pseudo_heading

    def parse(self, raw: RawDocument) -> list[ContentBlock]:
        lines = _decode(raw).splitlines(keepends=True)
        blocks: list[ContentBlock] = []
        pending: list[str] = []
        kind, start = "paragraph", 1
        fence_marker = ""
        quote_fence_marker = ""
        real_heading_level = 1

        def flush():
            nonlocal pending
            joined = "".join(pending)
            text = joined.strip("\n")
            block_kind, metadata = kind, {}
            if kind == "quote":
                first, _, body = joined.partition("\n")
                callout = self._callouts.get(first.strip())
                if callout:
                    block_kind = "callout"
                    level, label = callout
                    metadata = {"level": level}
                    body = body.rstrip("\n")
                    text = label + ("\n" + body if body else "")
            if text.strip():
                blocks.append(ContentBlock(
                    block_kind, text, ordinal=len(blocks) + 1, metadata=metadata,
                    locator={"line_start": start, "line_end": start + len(pending) - 1},
                ))
            pending = []

        for number, line in enumerate(lines, 1):
            bare = line.rstrip("\n")
            quote = self._quote.match(bare)
            if not quote:
                quote_fence_marker = ""
            elif not fence_marker:
                quoted_fence = self._fence.match(quote.group(1))
                if quote_fence_marker or quoted_fence:
                    if pending and kind != "quote":
                        flush()
                    if not pending:
                        kind, start = "quote", number
                    pending.append(quote.group(1) + ("\n" if line.endswith("\n") else ""))
                    if not quote_fence_marker:
                        quote_fence_marker = quoted_fence.group(1)
                    elif quoted_fence and quoted_fence.group(1)[0] == quote_fence_marker[0] and (
                        len(quoted_fence.group(1)) >= len(quote_fence_marker) and not quoted_fence.group(2).strip()
                    ):
                        quote_fence_marker = ""
                    continue
            fence = self._fence.match(bare)
            if fence_marker:
                pending.append(line)
                if fence and fence.group(1)[0] == fence_marker[0] and (
                    len(fence.group(1)) >= len(fence_marker) and not fence.group(2).strip()
                ):
                    flush()
                    fence_marker = ""
                continue
            if fence:
                flush()
                kind, start, fence_marker = "code", number, fence.group(1)
                pending.append(line)
                continue
            image = self._image.fullmatch(bare.strip())
            if image:
                flush()
                blocks.append(ContentBlock(
                    "image", _image_text(image.group(1)), ordinal=len(blocks) + 1,
                    locator={"line_start": number, "line_end": number},
                    metadata={"src": image.group(2).strip("<>")},
                ))
                continue
            bare = self._image.sub(lambda match: _image_text(match.group(1)), bare)
            line = bare + ("\n" if line.endswith("\n") else "")
            heading = self._heading.match(bare)
            if self._empty_heading.fullmatch(bare) or (heading and not heading.group(2).strip()):
                flush()
                continue
            bold_heading = re.fullmatch(r"\s*\*\*(.+?)\*\*\s*", bare)
            if bold_heading and self.pseudo_heading == "nested_label":
                label = bold_heading.group(1).strip()
                if not label or len(label) > 30 or re.search(r"[，。；！？,;!?]", label):
                    bold_heading = None
            if heading or bold_heading:
                flush()
                if heading:
                    real_heading_level = len(heading.group(1))
                blocks.append(ContentBlock(
                    "heading", self._link.sub(r"\1", heading.group(2) if heading else bold_heading.group(1)),
                    level=real_heading_level if heading else (
                        2 if self.pseudo_heading == "level2" else min(real_heading_level + 1, 6)
                    ),
                    ordinal=len(blocks) + 1, locator={"line_start": number, "line_end": number},
                ))
                continue
            if not bare.strip():
                flush()
                continue
            quote = self._quote.match(bare)
            next_kind = "quote" if quote else "table" if bare.lstrip().startswith("|") else (
                "list" if self._list.match(bare) else "paragraph"
            )
            if pending and next_kind != kind:
                flush()
            if not pending:
                kind, start = next_kind, number
            pending.append(quote.group(1) + ("\n" if line.endswith("\n") else "") if quote else line)
        flush()
        return blocks


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)

    def text(self) -> str:
        if self.tag in {"script", "style", "svg", "noscript"}:
            return ""
        if self.tag == "br":
            return "\n"
        if self.tag == "img":
            return _image_text(self.attrs.get("alt") or "")
        return "".join(child if isinstance(child, str) else child.text() for child in self.children)

    def find(self, predicate):
        if predicate(self):
            return self
        for child in self.children:
            if isinstance(child, _Node):
                result = child.find(predicate)
                if result is not None:
                    return result
        return None


class _DOMParser(HTMLParser):
    _void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in self._void:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


class HtmlParser:
    """微信优先读取 js_content，其他 HTML 读取 body；保留表头、代码及图片占位。"""

    _containers = {"root", "html", "body", "div", "section", "article", "ul", "ol", "table", "thead", "tbody", "tfoot"}
    _blocks = {"p", "li", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def parse(self, raw: RawDocument) -> list[ContentBlock]:
        dom = _DOMParser()
        dom.feed(_decode(raw))
        dom.close()
        root = dom.root.find(lambda node: node.attrs.get("id") == "js_content")
        if root is None:
            root = dom.root.find(lambda node: node.tag == "body") or dom.root
        blocks: list[ContentBlock] = []

        def emit(kind, text, level=None):
            if text.strip():
                ordinal = len(blocks) + 1
                blocks.append(ContentBlock(
                    kind, text, level=level, ordinal=ordinal, locator={"block": ordinal},
                ))

        def walk(node: _Node):
            if node.tag in {"script", "style", "svg", "noscript", "head"}:
                return
            nested_blocks = any(
                isinstance(child, _Node) and child.find(lambda n: n.tag in self._blocks) is not None
                for child in node.children
            )
            if node.tag == "tr":
                cells = [child for child in node.children if isinstance(child, _Node) and child.tag in {"td", "th"}]
                emit("table", "| " + " | ".join(_normal_text(cell.text()) for cell in cells) + " |")
                return
            if node.tag == "pre":
                emit("code", node.text().strip("\n"))
                return
            if node.tag in self._blocks and not nested_blocks:
                text = _normal_text(node.text())
                if node.tag.startswith("h") and node.tag[1:].isdigit():
                    emit("heading", text, int(node.tag[1:]))
                else:
                    def emphasized(child):
                        if child.tag in {"strong", "b"}:
                            return child.text()
                        return "".join(emphasized(part) for part in child.children if isinstance(part, _Node))

                    strong_text = _normal_text(emphasized(node))
                    bracket_heading = re.fullmatch(r"【[^【】\n]{1,60}】", text)
                    heading = bool(len(text) <= 100 and (strong_text == text or bracket_heading))
                    emit("heading" if heading else "list" if node.tag == "li" else "paragraph", text, 2 if heading else None)
                return
            if nested_blocks or node.tag in self._containers:
                inline: list[str] = []
                for child in node.children:
                    if isinstance(child, str):
                        inline.append(child)
                    elif child.tag in self._blocks or child.tag in self._containers or child.find(
                        lambda n: n.tag in self._blocks
                    ) is not None:
                        emit("paragraph", _normal_text("".join(inline)))
                        inline = []
                        walk(child)
                    elif child.tag not in {"script", "style", "svg", "noscript", "head"}:
                        inline.append(child.text())
                emit("paragraph", _normal_text("".join(inline)))
            else:
                emit("paragraph", _normal_text(node.text()))

        walk(root)
        return blocks


def _normal_text(text: str) -> str:
    return "\n".join(re.sub(r"[\t \xa0]+", " ", line).strip() for line in text.split("\n")).strip()


class ParserRegistry:
    """媒体类型到解析器的显式注册表，可直接作为 ParseStep 的 Parser。"""

    def __init__(self, parsers: dict[str, Parser] | None = None):
        self._parsers = dict(parsers) if parsers is not None else {
            "text/html": HtmlParser(), "text/markdown": MarkdownParser(), "text/plain": MarkdownParser(),
        }

    def register(self, media_type: str, parser: Parser):
        if media_type in self._parsers:
            raise ValueError(f"解析器已注册: {media_type}")
        self._parsers[media_type] = parser

    def parse(self, raw: RawDocument) -> list[ContentBlock]:
        media_type = raw.media_type.split(";", 1)[0].strip().lower()
        parser = self._parsers.get(media_type)
        if parser is None:
            raise DomainError("UNSUPPORTED_MEDIA_TYPE", "不支持该原文格式")
        return parser.parse(raw)
