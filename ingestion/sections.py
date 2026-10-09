"""按章节树规划父段，再按自然块合并教程检索文本。"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace

from contracts.types import RawDocument
from ingestion.preprocessing import ContentBlock, SemanticContext, SemanticEvidence
from ingestion.strategies import _join, _keeps_with, _key


@dataclass(frozen=True)
class SectionProfile:
    content_type: str
    max_parent_chars: int
    min_parent_chars: int
    chunk_target_chars: int
    chunk_min_chars: int


TUTORIAL = SectionProfile("tutorial", 3000, 150, 500, 120)


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


def merge_blocks(blocks: list[ContentBlock], profile: SectionProfile) -> list[SemanticEvidence]:
    groups = []
    group = []
    occurrences = Counter({"正文": 1}) if blocks and blocks[0].kind != "heading" else Counter()
    section, section_key, number = "正文", _key("evidence", "正文"), 1

    def flush():
        nonlocal group, number
        if group:
            groups.append((f"{section_key}-{number}", section, group))
            group = []
            number += 1

    for block in blocks:
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
    flush()

    merged = []
    for key, section, group in groups:
        if merged and len(_join(group)) < profile.chunk_min_chars:
            merged[-1][2].extend(group)
        else:
            merged.append((key, section, group))
    return [SemanticEvidence(
        key=key, body=_join(group), locator=_locator(group), metadata={"section": section},
    ) for key, section, group in merged]


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
