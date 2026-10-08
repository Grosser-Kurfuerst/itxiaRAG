"""Embedding 输入预算控制，拆分结果仍是父段下同级 Evidence。"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Callable, Protocol, Sequence

from contracts.errors import DomainError
from contracts.types import ProcessedDocument
from ingestion.preprocessing import SemanticContext


class InputCounter(Protocol):
    def count(self, text: str) -> int: ...


class Utf8ByteCounter:
    """无本地 tokenizer 时控制 UTF-8 字节数，不声称是精确模型 token 数。"""

    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


class TokenizerCounter:
    """适配部署侧提供的 encode 函数；其中应包括模型所需的特殊 token。"""

    def __init__(self, encode: Callable[[str], Sequence]):
        self.encode = encode

    def count(self, text: str) -> int:
        return len(self.encode(text))


class BudgetChunker:
    """先按段落/句子边界拆普通文本；不可拆语义单元超限时明确拒绝。"""

    def __init__(self, max_input_units: int = 2400, counter: InputCounter | None = None):
        if isinstance(max_input_units, bool) or not isinstance(max_input_units, int) or max_input_units < 1:
            raise ValueError("max_input_units 必须为正整数")
        self.max_input_units = max_input_units
        self.counter = counter or Utf8ByteCounter()

    def _fits(self, title: str, body: str) -> bool:
        return len(body) <= 32000 and self.counter.count(f"{title}\n{body}") <= self.max_input_units

    def _split(self, title: str, body: str) -> list[tuple[int, int]]:
        spans = []
        start = 0
        boundaries = [m.end() for m in re.finditer(r"\n\s*\n|[。！？!?](?:\s*)", body)]
        line_breaks = [m.end() for m in re.finditer(r"\n", body)]
        while start < len(body):
            # 二分找一个满足预算的前缀；最后仍逐条验证，不依赖 token 严格单调。
            low, high, best = start + 1, min(len(body), start + 32000), start
            while low <= high:
                mid = (low + high) // 2
                if self._fits(title, body[start:mid]):
                    best, low = mid, mid + 1
                else:
                    high = mid - 1
            if best == start:
                raise DomainError("INPUT_BUDGET_TOO_SMALL", "父段标题或单字符超过输入预算，请调整预算或标题")
            if best < len(body):
                preferred = [end for end in boundaries if start < end <= best and body[start:end].strip()]
                if not preferred:
                    # 没有段落/句子边界时退回换行，表格行和列表项尽量保持完整。
                    preferred = [end for end in line_breaks if start < end <= best and body[start:end].strip()]
                if preferred:
                    best = preferred[-1]
            if not body[start:best].strip():
                # 无语义的空白段不独立建 Evidence，避免丢失空白后产生错误覆盖。
                raise DomainError("INPUT_BUDGET_TOO_SMALL", "输入预算不足以容纳有效正文")
            spans.append((start, best))
            if len(spans) > 100:
                raise DomainError("PREPROCESS_LIMIT_EXCEEDED", "拆分后单个父段超过 100 个子块")
            start = best
        return spans

    def chunk(self, units: list[SemanticContext]) -> list[SemanticContext]:
        if len(units) > 100:
            raise DomainError("PREPROCESS_LIMIT_EXCEEDED", "整篇超过 100 个父段")
        result = []
        total = 0
        for unit in units:
            if len(unit.body) > 100000:
                raise DomainError("PREPROCESS_LIMIT_EXCEEDED", "父段正文超过 100000 字符")
            children = []
            search_start = 0
            for child in unit.children:
                offset = unit.body.find(child.body, search_start)
                if offset < 0:
                    raise DomainError("INVALID_PREPROCESS_STRUCTURE", "子块正文未出现在所属父段中")
                search_start = offset + len(child.body)
                if self._fits(unit.title, child.body):
                    spans = [(0, len(child.body))]
                elif child.atomic:
                    raise DomainError(
                        "SEMANTIC_UNIT_TOO_LARGE",
                        "完整测试条件/结果、推荐理由、表格或代码超过输入预算，请调整预算或语义边界",
                    )
                else:
                    spans = self._split(unit.title, child.body)
                for number, (start, end) in enumerate(spans, 1):
                    text = child.body[start:end]
                    if not self._fits(unit.title, text):
                        raise DomainError("INPUT_BUDGET_EXCEEDED", "拆分后的输入仍超过预算")
                    children.append(replace(
                        child,
                        key=child.key if len(spans) == 1 else f"{child.key}-part-{number}",
                        body=text,
                        locator={**child.locator, "parent_char_start": offset + start, "parent_char_end": offset + end},
                    ))
            if len(children) > 100:
                raise DomainError("PREPROCESS_LIMIT_EXCEEDED", "拆分后单个父段超过 100 个子块")
            total += len(children)
            if total > 1000:
                raise DomainError("PREPROCESS_LIMIT_EXCEEDED", "拆分后整篇超过 1000 个子块")
            result.append(replace(unit, children=children))
        return result

    def validate(self, document: ProcessedDocument):
        """DTO 构建/校验后再次核对实际编码文本，供 ValidateStep 注入。"""
        for parent in document.contexts:
            for child in parent.children:
                if not self._fits(parent.title, child.body):
                    raise DomainError("INPUT_BUDGET_EXCEEDED", "最终文档的模型输入超过预算")
