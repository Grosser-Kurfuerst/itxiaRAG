"""内容类型策略：同一套 Parser 可服务评测、购买指南和经验文档。"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from contracts.errors import DomainError
from contracts.types import RawDocument
from ingestion.preprocessing import ContentBlock, SemanticContext, SemanticEvidence


_REVIEW_SECTIONS = {
    "配置", "配置参数", "规格", "优缺点", "优点", "缺点", "升级建议", "购买建议",
    "散热分析", "散热测试", "散热", "测试条件", "测试结果", "测试环境", "测试方法",
    "屏幕", "接口", "噪音", "续航", "总结", "结论", "猪王的良心结语",
}
_PROTECTED_SECTIONS = {
    "散热分析", "散热测试", "散热", "测试条件", "测试结果", "测试环境", "测试方法",
    "购买建议", "推荐理由", "不推荐理由",
}
_GLOBAL_GUIDE_SECTIONS = {"价格警告", "全局建议", "本期改动", "产品分类", "FAQ", "常见问题", "测评计划"}


def _label(text: str) -> str:
    return text.strip().strip("【】[]：: ")


def _key(prefix: str, title: str, occurrence: int = 1) -> str:
    # 同名标题用出现次数区分，正文变化、无关段落插入不改变其他 key。
    digest = hashlib.sha256(title.encode()).hexdigest()[:16]
    return f"{prefix}-{digest}" + (f"-{occurrence}" if occurrence > 1 else "")


def _join(blocks: list[ContentBlock]) -> str:
    return "\n\n".join(block.text for block in blocks if block.text.strip())


def _children(blocks: list[ContentBlock]) -> list[SemanticEvidence]:
    groups: list[list[ContentBlock]] = []
    group: list[ContentBlock] = []
    protected_level: int | None = None
    for block in blocks:
        # 保留“条件 + 结果”以及连续表格行/代码内容在所属小节里。
        if block.kind == "heading":
            inside_protected = protected_level is not None and (block.level or 99) > protected_level
            if not inside_protected:
                if group:
                    groups.append(group)
                    group = []
                protected_level = (block.level or 2) if _label(block.text) in _PROTECTED_SECTIONS else None
        group.append(block)
    if group:
        groups.append(group)
    occurrences = Counter()
    children = []
    for group in groups:
        section = group[0].text if group[0].kind == "heading" else "正文"
        occurrences[section] += 1
        atomic = _label(section) in _PROTECTED_SECTIONS or any(b.kind in {"table", "code"} for b in group)
        children.append(SemanticEvidence(
            key=_key("evidence", section, occurrences[section]), body=_join(group),
            locator={"block_start": group[0].ordinal, "block_end": group[-1].ordinal},
            metadata={"section": section}, atomic=atomic,
        ))
    return children


def _context(title: str, blocks: list[ContentBlock], key: str, *, metadata=None,
             make_children=_children) -> SemanticContext:
    body = _join(blocks)
    content = blocks[1:] if blocks and blocks[0].kind == "heading" and blocks[0].text == title else blocks
    children = make_children(content)
    if not children:
        # 标题独立存在时仍构成可引用的原文，不生成空 children。
        body = title
        children = [SemanticEvidence(_key("evidence", "标题"), title)]
    return SemanticContext(
        key=key, title=title, body=body, children=children, metadata=dict(metadata or {}),
        locator={"block_start": blocks[0].ordinal, "block_end": blocks[-1].ordinal} if blocks else {},
    )


def _without_document_heading(blocks: list[ContentBlock]) -> tuple[str | None, list[ContentBlock]]:
    if blocks and blocks[0].kind == "heading" and blocks[0].level == 1:
        return blocks[0].text, blocks[1:]
    return None, blocks


def _split_sections(blocks: list[ContentBlock], boundary) -> list[tuple[str, list[ContentBlock]]]:
    sections: list[tuple[str, list[ContentBlock]]] = []
    title, group = "前言", []
    for block in blocks:
        if boundary(block):
            if group:
                sections.append((title, group))
            title, group = block.text, [block]
        else:
            group.append(block)
    if group:
        sections.append((title, group))
    return sections


def _make_contexts(sections, *, content_type: str, make_children=_children) -> list[SemanticContext]:
    occurrences = Counter()
    contexts = []
    for title, blocks, metadata in sections:
        occurrences[title] += 1
        contexts.append(_context(title, blocks, _key("context", title, occurrences[title]), metadata={
            "content_type": content_type, **metadata,
        }, make_children=make_children))
    return contexts


class HeadingSectionsStrategy:
    """通用章节策略；可配置父段标题级别，段内小标题形成 Evidence。"""

    content_type = "section"

    def __init__(self, section_level: int = 2):
        if not 1 <= section_level <= 6:
            raise ValueError("section_level 必须在 1～6 之间")
        self.section_level = section_level

    def build(self, blocks: list[ContentBlock], raw: RawDocument) -> list[SemanticContext]:
        doc_title, content = _without_document_heading(blocks)
        if not content:
            content = blocks
        sections = _split_sections(content, lambda b: b.kind == "heading" and (b.level or 99) <= self.section_level)
        fallback = raw.metadata.get("title") or doc_title or "正文"
        return _make_contexts([
            (str(fallback) if title == "前言" and len(sections) == 1 else title, group, {})
            for title, group in sections
        ], content_type=self.content_type)


_MISSING_IMAGES = re.compile(r"(?:\[图片：未提供文字说明\]\s*)+")
_ENUMERATED = re.compile(r"\d+\s*(?:[，,、)）]|\.(?!\d))")


def _is_section_label(block: ContentBlock) -> bool:
    # 栏目名才作为切块断点；整句加粗的结论/数据不是断点，误判只影响检索块边界。
    text = block.text.strip()
    if re.fullmatch(r"【[^【】\n]{1,60}】", text):
        return True
    return block.kind == "heading" and len(text) <= 30 and not re.search(r"[，。；,;]", text)


def _keeps_with(previous: ContentBlock, block: ContentBlock) -> bool:
    # 引导句（：）和未完的并列句（；）与下一段相连，例如噪音数据与测试环境。
    if _is_section_label(previous) or previous.text.rstrip().endswith(("：", ":", "；", ";")):
        return True
    if previous.kind == block.kind and block.kind in {"list", "table"}:
        return True
    return bool(_ENUMERATED.match(previous.text) and _ENUMERATED.match(block.text))


class ReviewStrategy:
    """单机一个父段，多机型通过 entity_headings 显式指定机型标题。

    子块只服务召回，不解析小节语义：按原文顺序合并自然段，检索命中后返回整台电脑的父段。
    长度上限仍由 Chunker 按模型预算检查，超长块按段落/句子拆分。
    """

    def __init__(self, target_chars: int = 400, min_chars: int = 120):
        if isinstance(target_chars, bool) or not isinstance(target_chars, int) or target_chars < 1:
            raise ValueError("target_chars 必须为正整数")
        if isinstance(min_chars, bool) or not isinstance(min_chars, int) or not 0 <= min_chars <= target_chars:
            raise ValueError("min_chars 必须在 0～target_chars 之间")
        self.target_chars = target_chars
        self.min_chars = min_chars

    def _chunks(self, blocks: list[ContentBlock]) -> list[SemanticEvidence]:
        def size(group):
            return len(_join(group))

        groups: list[list[ContentBlock]] = []
        group: list[ContentBlock] = []
        section_level: int | None = None
        for block in blocks:
            # 更深的子标题（如“散热分析”下的“测试结果”）按普通段落处理，只在超出目标长度时断开。
            starts_section = _is_section_label(block) and (section_level is None or (block.level or 2) <= section_level)
            if group and not _keeps_with(group[-1], block) and (
                starts_section or size(group + [block]) > self.target_chars
            ):
                groups.append(group)
                group = []
            if starts_section:
                # 正文中的一级标题照常断开，但不让后续二级栏目变成“子标题”。
                section_level = max(block.level or 2, 2)
            group.append(block)
        if group:
            groups.append(group)
        # 过短的块（包括短栏目）并回前一块，过短的首块并入后一块，避免无上下文的碎片单独生成向量。
        limit = self.target_chars + self.min_chars
        merged: list[list[ContentBlock]] = []
        for group in groups:
            if merged and size(group) < self.min_chars and size(merged[-1] + group) <= limit:
                merged[-1] = merged[-1] + group
            else:
                merged.append(group)
        if len(merged) > 1 and size(merged[0]) < self.min_chars and size(merged[0] + merged[1]) <= limit:
            merged[:2] = [merged[0] + merged[1]]
        return [
            SemanticEvidence(
                key=f"evidence-chunk-{number}", body=_join(group),
                locator={"block_start": group[0].ordinal, "block_end": group[-1].ordinal},
            )
            for number, group in enumerate(merged, 1)
        ]

    def build(self, blocks: list[ContentBlock], raw: RawDocument) -> list[SemanticContext]:
        # 只含无说明图片的段落只保留文档警告，不进入父段和检索文本。
        blocks = [block for block in blocks if not _MISSING_IMAGES.fullmatch(block.text.strip())]
        _, content = _without_document_heading(blocks)
        entities = raw.metadata.get("entity_headings", [])
        if not isinstance(entities, list) or any(not isinstance(item, str) for item in entities):
            raise DomainError("INVALID_ENTITY_BOUNDARY", "entity_headings 必须是标题字符串列表")
        if len(entities) != len(set(entities)):
            raise DomainError("INVALID_ENTITY_BOUNDARY", "entity_headings 不能包含重复标题")
        if entities:
            found = {b.text for b in content if b.kind == "heading" and b.text in entities}
            if set(entities) != found:
                raise DomainError("ENTITY_BOUNDARY_NOT_FOUND", "部分机型标题未在原文找到")
            sections = _split_sections(content, lambda b: b.kind == "heading" and b.text in entities)
            return _make_contexts([(title, group, {}) for title, group in sections],
                                  content_type="review", make_children=self._chunks)
        # 父段标题会拼入每个子块的检索文本，必须是机型名而不是文章标题。
        title = str(raw.metadata.get("entity_title") or "").strip()
        if not title:
            raise DomainError("ENTITY_TITLE_REQUIRED", "单机评测须在 metadata.entity_title 提供机型名")
        content = content or blocks
        if not content:
            return []
        # 机型 key 与文章标题分开；可在采集侧指定稳定 entity_key。
        key = _key("context", str(raw.metadata.get("entity_key") or title))
        return [_context(title, content, key, metadata={"content_type": "review"}, make_children=self._chunks)]


class PurchaseGuideStrategy:
    """预算作为推荐卡的背景，机型推荐卡单独为父段，全局建议保留独立父段。"""

    _budget = re.compile(
        r"(?:(?:预算|价位|价格区间)\s*[:：]?\s*)?[≤≥<>]?\s*\d[\d,，]*"
        r"(?:\s*[～~—\-至]\s*\d[\d,，]*)?\s*元"
        r"(?:以下|以上|以内|左右|档|价位)?(?:（[^）]*）)?"
    )

    def build(self, blocks: list[ContentBlock], raw: RawDocument) -> list[SemanticContext]:
        _, content = _without_document_heading(blocks)
        content = content or blocks
        sections = []
        group: list[ContentBlock] = []
        title, budget = "全局建议", None
        card_level: int | None = None
        group_budget: str | None = None

        def flush():
            nonlocal group
            if group:
                metadata = {"budget": group_budget} if group_budget else {}
                sections.append((title, group, metadata))
            group = []

        for block in content:
            if block.kind != "heading":
                group.append(block)
                continue
            label, level = _label(block.text), block.level or 2
            if level <= 2 and self._budget.fullmatch(label):
                flush()
                budget, card_level = block.text, level + 1
                title, group, group_budget = block.text, [block], block.text
                continue
            if label in _REVIEW_SECTIONS and group:
                group.append(block)
                continue
            is_boundary = (card_level is None and level <= 2) or (
                card_level is not None and level <= card_level
            )
            if is_boundary:
                # 比预算更浅的标题离开当前预算；同级粗体机型也可成为卡片。
                flush()
                if card_level is not None and level <= card_level - 1 and label in _GLOBAL_GUIDE_SECTIONS:
                    budget, card_level = None, None
                group_budget = budget
                title, group = block.text, [block]
            else:
                group.append(block)
        flush()
        contexts = _make_contexts(sections, content_type="purchase_guide")
        global_guidance = [p.body for p in contexts if _label(p.title) in {"价格警告", "全局建议", "本期改动"}]
        for context in contexts:
            if _label(context.title) not in _GLOBAL_GUIDE_SECTIONS and not self._budget.fullmatch(_label(context.title)):
                context.metadata["entity_title"] = context.title
                if global_guidance:
                    context.metadata["global_guidance"] = global_guidance
                context.warnings.append("价格与推荐仅代表来源日期，请结合预算和该文全局建议。")
        return contexts


class ExperienceCaseStrategy(HeadingSectionsStrategy):
    """语雀经验文档按章节/案例组织父段，复用通用实现。"""

    content_type = "experience_case"
