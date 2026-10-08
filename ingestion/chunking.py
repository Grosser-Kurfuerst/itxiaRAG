"""Embedding 输入预算控制，拆分结果仍是父段下同级 Evidence。"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Callable, Protocol, Sequence

from contracts.errors import DomainError
from contracts.types import ProcessedDocument, evidence_input
from ingestion.preprocessing import SemanticContext


_TABLE_ROW = re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.M)
_TABLE_SEPARATOR = re.compile(r"[ \t]*\|(?:[ \t]*:?-+:?[ \t]*\|)+[ \t]*")


def _table_layout(body: str) -> tuple[list[tuple[int, int]], list[tuple[int, int, str]]]:
    """识别连续的管道表格行，返回所有行区间和 (表头结束, 表格结束, 表头文本)。"""
    rows = [(m.start(), m.end()) for m in _TABLE_ROW.finditer(body)]
    tables: list[list[tuple[int, int]]] = []
    for row in rows:
        if tables and not body[tables[-1][-1][1]:row[0]].strip():
            tables[-1].append(row)
        else:
            tables.append([row])
    headers = []
    for table in tables:
        header_rows = 2 if len(table) > 2 and _TABLE_SEPARATOR.fullmatch(body[slice(*table[1])]) else 1
        header_end = table[header_rows - 1][1]
        if len(table) > header_rows:
            headers.append((header_end, table[-1][1], body[table[0][0]:header_end]))
    return rows, headers


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

    def _fits(self, title: str, body: str, prefix: str = "") -> bool:
        return len(body) <= 32000 and self.counter.count(evidence_input(title, body, prefix)) <= self.max_input_units

    def _longest_fit(self, title: str, prefix: str, body: str, start: int) -> int:
        # 二分找一个满足预算的前缀；最后仍逐条验证，不依赖 token 严格单调。
        low, high, best = start + 1, min(len(body), start + 32000), start
        while low <= high:
            mid = (low + high) // 2
            if self._fits(title, body[start:mid], prefix):
                best, low = mid, mid + 1
            else:
                high = mid - 1
        return best

    @staticmethod
    def _cut(body: str, start: int, best: int, *candidates: list[int]) -> int:
        # 按剩余长度均分，避免只含标题或尾句的极短子块；断点不早于目标长度的一半，优先段落/句子，其次换行。
        remaining, window = len(body) - start, best - start
        pieces = -(-remaining // window)
        target = start + -(-remaining // pieces)
        floor = start + max(1, (target - start) // 2)
        for ends in candidates:
            usable = [end for end in ends if floor <= end <= best and body[start:end].strip()]
            if usable:
                return min(usable, key=lambda end: (abs(end - target), -end))
        return target

    def _split(self, title: str, body: str, base_prefix: str = "") -> list[tuple[int, int, str]]:
        rows, headers = _table_layout(body)

        def outside_rows(end):
            # 表格只在行之间断开，单元格内的句号不作为断点。
            return not any(row_start < end < row_end for row_start, row_end in rows)

        boundaries = [m.end() for m in re.finditer(r"\n\s*\n|[。！？!?](?:\s*)", body) if outside_rows(m.end())]
        line_breaks = [m.end() for m in re.finditer(r"\n", body) if outside_rows(m.end())]
        spans = []
        start = 0
        while start < len(body):
            # 从表格数据行开始的子块在编码文本中附带表头，正文与定位仍是原始数据行。
            header = next((text for header_end, table_end, text in headers if header_end < start < table_end), "")
            prefix = "\n".join(part for part in (base_prefix, header) if part)
            best = self._longest_fit(title, prefix, body, start)
            if header and best < min(row_end for row_start, row_end in rows if row_end > start):
                # 表头加一整行数据都放不下时退回不带表头，避免为表头把数据行切碎。
                prefix = base_prefix
                best = self._longest_fit(title, prefix, body, start)
            if best == start:
                raise DomainError("INPUT_BUDGET_TOO_SMALL", "父段标题或单字符超过输入预算，请调整预算或标题")
            end = self._cut(body, start, best, boundaries, line_breaks) if best < len(body) else best
            if not body[start:end].strip():
                # 无语义的空白段不独立建 Evidence，避免丢失空白后产生错误覆盖。
                raise DomainError("INPUT_BUDGET_TOO_SMALL", "输入预算不足以容纳有效正文")
            spans.append((start, end, prefix))
            if len(spans) > 100:
                raise DomainError("PREPROCESS_LIMIT_EXCEEDED", "拆分后单个父段超过 100 个子块")
            start = end
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
                if self._fits(unit.title, child.body, child.retrieval_prefix):
                    spans = [(0, len(child.body), child.retrieval_prefix)]
                elif child.atomic:
                    raise DomainError(
                        "SEMANTIC_UNIT_TOO_LARGE",
                        "完整测试条件/结果、推荐理由、表格或代码超过输入预算，请调整预算或语义边界",
                    )
                else:
                    spans = self._split(unit.title, child.body, child.retrieval_prefix)
                for number, (start, end, prefix) in enumerate(spans, 1):
                    text = child.body[start:end]
                    if not self._fits(unit.title, text, prefix):
                        raise DomainError("INPUT_BUDGET_EXCEEDED", "拆分后的输入仍超过预算")
                    children.append(replace(
                        child,
                        key=child.key if len(spans) == 1 else f"{child.key}-part-{number}",
                        body=text, retrieval_prefix=prefix,
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
                if not self._fits(parent.title, child.body, child.retrieval_prefix):
                    raise DomainError("INPUT_BUDGET_EXCEEDED", "最终文档的模型输入超过预算")
