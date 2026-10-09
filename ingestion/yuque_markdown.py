"""语雀 Markdown 的逐行规范化；保留行号，不读取平台或图片。"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from contracts.types import RawDocument
from ingestion.parsers import MarkdownParser, _decode, _DOMParser
from ingestion.preprocessing import ContentBlock


@dataclass
class _NormalizeState:
    in_callout: bool = False


def _strip_styles(line, _state):
    return re.sub(
        r"</?(?:font|span|u|sup|sub|mark|strong|em)(?:\s+[^<>]*?)?\s*/?>",
        "", line, flags=re.IGNORECASE,
    )


def _table_breaks(line, _state):
    if line.lstrip().startswith("|"):
        return re.sub(r"<br\s*/?\s*>", "；", line, flags=re.IGNORECASE)
    return line


def _callout(line, state):
    marker = re.fullmatch(r":::(warning|tips|info|success|danger|color\d+)\s*", line.strip(), re.IGNORECASE)
    if marker:
        state.in_callout = True
        level = {"warning": "WARNING", "danger": "CAUTION"}.get(marker.group(1).lower(), "NOTE")
        return f"> [!{level}]"
    if state.in_callout and line.strip() == ":::":
        state.in_callout = False
        return ""
    return line


def _details(line, _state):
    if not re.fullmatch(r"\s*<details\b[^>]*>.*</details>\s*", line, re.IGNORECASE):
        return line
    dom = _DOMParser()
    dom.feed(line)
    dom.close()
    summary = dom.root.find(lambda node: node.tag == "summary")

    def text(node, *, body=False):
        if isinstance(node, str):
            return node
        if node.tag in {"img", "script", "style", "svg", "noscript"} or (body and node.tag == "summary"):
            return ""
        if node.tag == "br":
            return " "
        value = "".join(text(child, body=body) for child in node.children)
        return value + " " if node.tag in {"p", "div", "li"} else value

    title = " ".join(text(summary).split()) if summary is not None else ""
    body = " ".join(text(dom.root, body=True).split())
    return f"**{title}**：{body}" if title else body


def _html_image(line, _state):
    if not re.fullmatch(r"\s*<img\b[^<>]*>\s*", line, re.IGNORECASE):
        return line
    dom = _DOMParser()
    dom.feed(line)
    dom.close()
    image = dom.root.find(lambda node: node.tag == "img")
    alt, src = image.attrs.get("alt") or "", image.attrs.get("src") or ""
    return f"![{alt}]({src})"


def _empty_structures(line, _state):
    line = line.replace("****", "")
    if not line.strip() or re.fullmatch(r"\s*(?:#{1,6}\s*|\*\*\s*\*\*|>\s*)", line):
        return ""
    return line


def _anchor_links(line, _state):
    return re.sub(r"(?<!!)\[([^\]\n]*)\]\(#[^)\s]*\)", r"\1", line)


def _strikethrough(line, _state):
    # 语雀把删除线内的行内代码写成 ~~a~~`~~b~~`~~c~~，只含删除内容的代码一并删除。
    line = re.sub(r"~~.*?~~", "\0", line)
    return re.sub(r"`\0+`", "", line).replace("\0", "")


_LINE_RULES = [
    _strip_styles, _table_breaks, _callout, _details, _html_image,
    _anchor_links, _strikethrough, _empty_structures,
]


def normalize_yuque(text: str) -> str:
    state = _NormalizeState()
    fence_marker = ""
    normalized = []
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        ending = line[len(bare):]
        fence = MarkdownParser._fence.match(bare)
        quoted = state.in_callout
        if fence_marker:
            if fence and fence.group(1)[0] == fence_marker[0] and (
                len(fence.group(1)) >= len(fence_marker) and not fence.group(2).strip()
            ):
                fence_marker = ""
        elif fence:
            fence_marker = fence.group(1)
        else:
            for rule in _LINE_RULES:
                bare = rule(bare, state)
            quoted = quoted and state.in_callout
        if quoted:
            bare = "> " + bare
        # 最后一行被清空时仍保留这一行，供通用解析器定位。
        normalized.append(bare + (ending or ("\n" if not bare else "")))
    return "".join(normalized)


class YuqueMarkdownParser:
    """方言规范化后复用通用解析器，默认把短粗体栏目嵌入当前章节。"""

    def __init__(self, inner: MarkdownParser | None = None):
        self.inner = inner if inner is not None else MarkdownParser(pseudo_heading="nested_label")

    def parse(self, raw: RawDocument) -> list[ContentBlock]:
        text = normalize_yuque(_decode(raw))
        return self.inner.parse(replace(raw, content=text.encode("utf-8")))
