"""按章节树规划父段，再按自然块合并教程与知识的检索文本。"""

from __future__ import annotations

import re
from collections import Counter
from itertools import groupby
from dataclasses import dataclass, field, replace

from contracts.types import RawDocument
from ingestion.chunking import _TABLE_SEPARATOR
from ingestion.preprocessing import ContentBlock, SemanticContext, SemanticEvidence
from ingestion.strategies import _join, _keeps_with, _key


@dataclass(frozen=True)
class SectionProfile:
    content_type: str
    max_parent_chars: int
    min_parent_chars: int
    chunk_target_chars: int
    chunk_min_chars: int
    table_rows_as_children: bool = False


TUTORIAL = SectionProfile("tutorial", 3000, 150, 500, 120)
KNOWLEDGE = SectionProfile("knowledge", 2500, 150, 400, 120, table_rows_as_children=True)


def _content_size(blocks: list[ContentBlock]) -> int:
    return sum(len(re.sub(r"\s+", "", block.text)) for block in blocks if block.kind != "heading")


@dataclass
class SectionNode:
    heading: ContentBlock | None
    level: int
    blocks: list[ContentBlock] = field(default_factory=list)
    children: list[SectionNode] = field(default_factory=list)

    def size(self) -> int:
        return _content_size(self.blocks) + sum(child.size() for child in self.children)


def build_tree(blocks: list[ContentBlock]) -> SectionNode:
    root = SectionNode(None, 0)
    stack = [root]
    for block in blocks:
        if block.kind == "heading":
            level = block.level or 2
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            node = SectionNode(block, level)
            stack[-1].children.append(node)
            stack.append(node)
        else:
            stack[-1].blocks.append(block)
    return root


def _subtree_blocks(node: SectionNode) -> list[ContentBlock]:
    blocks = ([node.heading] if node.heading else []) + node.blocks
    for child in node.children:
        blocks.extend(_subtree_blocks(child))
    return blocks


@dataclass
class _ParentSection:
    path: tuple[str, ...]
    blocks: list[ContentBlock]
    parent: SectionNode
    block_start: int
    key: str = ""


def plan_parents(root: SectionNode, profile: SectionProfile, document_title: str) -> list[_ParentSection]:
    # 唯一的包裹标题不进入章节路径；导语保留在虚拟根，允许逐层下降。
    while len(root.children) == 1 and _content_size(root.blocks) < profile.min_parent_chars:
        wrapper = root.children[0]
        if not wrapper.children:
            break
        root.blocks.extend(wrapper.blocks)
        root.children = wrapper.children

    planned = []
    if root.blocks:
        planned.append(_ParentSection((document_title,), list(root.blocks), root, root.blocks[0].ordinal))

    def visit(node, path, parent):
        path = (*path, node.heading.text)
        if node.size() <= profile.max_parent_chars or not node.children:
            planned.append(_ParentSection(path, _subtree_blocks(node), parent, node.heading.ordinal))
        else:
            if node.blocks:
                planned.append(_ParentSection(path, [node.heading, *node.blocks], parent, node.heading.ordinal))
            start = len(planned)
            for child in node.children:
                visit(child, path, node)
            if not node.blocks and len(planned) > start:
                # 没有导语父段时，祖先标题及其被过滤的图片归入第一个后代父段。
                planned[start].block_start = node.heading.ordinal

    for node in root.children:
        visit(node, (), root)

    occurrences = Counter()
    for section in planned:
        title = " > ".join(section.path)
        occurrences[title] += 1
        section.key = _key("context", title, occurrences[title])

    # 只合并同一上级下连续的父段，身份始终由接收方保留。
    index = 0
    while index < len(planned):
        section = planned[index]
        if _content_size(section.blocks) < profile.min_parent_chars:
            if index > 0 and planned[index - 1].parent is section.parent:
                planned[index - 1].blocks.extend(section.blocks)
                planned.pop(index)
                continue
            if index + 1 < len(planned) and planned[index + 1].parent is section.parent:
                planned[index + 1].blocks[:0] = section.blocks
                planned[index + 1].block_start = section.block_start
                planned.pop(index)
                continue
        index += 1
    return planned


def _locator(blocks: list[ContentBlock]) -> dict:
    locator = {"block_start": blocks[0].ordinal, "block_end": blocks[-1].ordinal}
    if "line_start" in blocks[0].locator:
        locator["line_start"] = blocks[0].locator["line_start"]
    if "line_end" in blocks[-1].locator:
        locator["line_end"] = blocks[-1].locator["line_end"]
    return locator


def _table_rows(table: list[ContentBlock]) -> list[ContentBlock]:
    # Markdown 表格是一个带行号的多行块，展开为逐行块并随行定位；HTML 表格每行已是一个块。
    rows = []
    for block in table:
        line_start = block.locator.get("line_start")
        if line_start is None:
            rows.append(block)
            continue
        rows.extend(
            replace(block, text=line, locator={"line_start": line_start + offset, "line_end": line_start + offset})
            for offset, line in enumerate(block.text.split("\n"))
        )
    return rows


def _join_rows(blocks: list[ContentBlock]) -> str:
    # 同一原文块内的行以换行相连，不同块以空行相连，结果仍是父段正文的连续片段。
    blocks = [block for block in blocks if block.text.strip()]
    text = blocks[0].text
    for previous, block in zip(blocks, blocks[1:]):
        text += ("\n" if block.ordinal == previous.ordinal else "\n\n") + block.text
    return text


def _row_groups(lead: list[ContentBlock], rows: list[ContentBlock], target: int) -> list[list[ContentBlock]]:
    """把表格数据行按目标长度分组；前置标题与表头归入第一组，保持各组在父段中连续。"""
    header_size = 2 if len(rows) > 2 and _TABLE_SEPARATOR.fullmatch(rows[1].text) else 1
    groups, group, has_data = [], [*lead, *rows[:header_size]], False
    for row in rows[header_size:]:
        if has_data and len(_join_rows([*group, row])) > target:
            groups.append(group)
            group = []
        group.append(row)
        has_data = True
    return [*groups, group]


def merge_blocks(blocks: list[ContentBlock], profile: SectionProfile) -> list[SemanticEvidence]:
    groups = []  # (key, section, blocks, 表头)；表头非空的是表格行组
    group = []
    occurrences = Counter({"正文": 1}) if blocks and blocks[0].kind != "heading" else Counter()
    section, section_key, number = "正文", _key("evidence", "正文"), 1

    def flush():
        nonlocal group, number
        if group:
            groups.append((f"{section_key}-{number}", section, group, ""))
            group = []
            number += 1

    def add(block):
        nonlocal section, section_key, number
        if block.kind == "heading":
            if group and group[-1].kind != "heading":
                flush()
            section = block.text
            occurrences[section] += 1
            section_key, number = _key("evidence", section, occurrences[section]), 1
        elif group and not (
            group[-1].kind == "heading" or block.kind == "callout" or _keeps_with(group[-1], block)
        ) and len(_join([*group, block])) > profile.chunk_target_chars:
            flush()
        group.append(block)

    for is_table, run in groupby(blocks, key=lambda block: block.kind == "table"):
        run = list(run)
        rows = _table_rows(run) if is_table and profile.table_rows_as_children else []
        if not rows or len(_join(run)) <= profile.chunk_target_chars:
            for block in run:
                add(block)
            continue
        # 长表格按行组成子块，尚无正文的标题随第一组；表头写入每组的检索前缀。
        lead = group if all(block.kind == "heading" for block in group) else []
        if not lead:
            flush()
        group = []
        for rows_group in _row_groups(lead, rows, profile.chunk_target_chars):
            groups.append((f"{section_key}-{number}", section, rows_group, rows[0].text.strip()))
            number += 1
    flush()

    merged = []
    for key, section, group, header in groups:
        if merged and not header and not merged[-1][3] and len(_join(group)) < profile.chunk_min_chars:
            merged[-1][2].extend(group)
        else:
            merged.append((key, section, group, header))
    return [SemanticEvidence(
        key=key, body=_join_rows(group) if header else _join(group), locator=_locator(group),
        metadata={"section": section}, retrieval_prefix=header,
    ) for key, section, group, header in merged]


def _title(path: tuple[str, ...]) -> str:
    title = " > ".join(path)
    return title if len(title) <= 200 else title[:99] + "…" + title[-100:]


class SectionedDocumentStrategy:
    def __init__(self, profile: SectionProfile):
        self.profile = profile

    def build(self, blocks: list[ContentBlock], raw: RawDocument) -> list[SemanticContext]:
        image_placeholder = "[图片：未提供文字说明]"
        content = []
        for block in blocks:
            if image_placeholder in block.text:
                text = "\n".join(
                    re.sub(r"[^\S\n]+", " ", line.replace(image_placeholder, "")).strip()
                    if image_placeholder in line else line
                    for line in block.text.split("\n")
                )
                if not text.strip():
                    continue
                block = replace(block, text=text)
            content.append(block)
        title = str(raw.metadata.get("title") or "未命名文档")
        sections = plan_parents(build_tree(content), self.profile, title)
        contexts = []
        for index, section in enumerate(sections):
            # 过滤的图片仍归属于原文区间；保留序号，不重新编号内容块。
            start = section.block_start if index else blocks[0].ordinal
            end = sections[index + 1].block_start - 1 if index + 1 < len(sections) else blocks[-1].ordinal
            original = [block for block in blocks if start <= block.ordinal <= end]
            contexts.append(SemanticContext(
                key=section.key, title=_title(section.path), body=_join(section.blocks),
                children=merge_blocks(section.blocks, self.profile), locator=_locator(original),
                metadata={
                    "content_type": self.profile.content_type, "section_path": list(section.path),
                    "omitted_images": sum(block.text.count(image_placeholder) for block in original),
                },
            ))
        return contexts
