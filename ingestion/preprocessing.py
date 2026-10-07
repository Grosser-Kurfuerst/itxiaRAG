"""可组合的文档预处理流水线。

预处理器在导入服务之外完成解析、语义分组和长度控制，最终仍只输出公共
``ProcessedDocument``。步骤是受信任的应用代码，由组合根按顺序装配。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Literal, Protocol

from contracts.serializers import validate_document
from contracts.types import ContextDraft, EvidenceDraft, ProcessedDocument, RawDocument


PreprocessStage = Literal["raw", "blocks", "units", "chunked", "document", "validated"]


@dataclass(frozen=True)
class ContentBlock:
    """解析器输出的最小内容块，不暴露给存储层。"""

    kind: str
    text: str
    level: int | None = None
    ordinal: int = 0
    locator: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticEvidence:
    key: str
    body: str
    locator: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    atomic: bool = False


@dataclass(frozen=True)
class SemanticContext:
    key: str
    title: str
    body: str
    children: list[SemanticEvidence]
    locator: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PreprocessContext:
    raw: RawDocument
    stage: PreprocessStage = "raw"
    blocks: list[ContentBlock] = field(default_factory=list)
    units: list[SemanticContext] = field(default_factory=list)
    document: ProcessedDocument | None = None
    warnings: list[str] = field(default_factory=list)


class PreprocessStep(Protocol):
    input_stage: PreprocessStage
    output_stage: PreprocessStage

    def process(self, context: PreprocessContext) -> PreprocessContext: ...


_STAGES = {"raw", "blocks", "units", "chunked", "document", "validated"}


def _set_stage(context: PreprocessContext, stage: PreprocessStage) -> PreprocessContext:
    context.stage = stage
    return context


class PreprocessPipeline:
    """按显式顺序执行预处理步骤，并在构造时拒绝不连贯的流程。"""

    def __init__(self, steps: list[PreprocessStep]):
        self.steps = tuple(steps)
        self._validate_steps()

    def _validate_steps(self):
        expected: PreprocessStage = "raw"
        for step in self.steps:
            if step.input_stage not in _STAGES or step.output_stage not in _STAGES:
                raise ValueError(f"步骤 {type(step).__name__} 声明了未知阶段")
            if step.input_stage != expected:
                raise ValueError(
                    f"步骤 {type(step).__name__} 的输入阶段为 {step.input_stage}，预期为 {expected}"
                )
            expected = step.output_stage
        if expected != "validated":
            raise ValueError("预处理流水线必须以 validated 阶段结束")

    def process(self, raw: RawDocument) -> ProcessedDocument:
        context = PreprocessContext(raw=raw)
        for step in self.steps:
            if context.stage != step.input_stage:
                raise TypeError(f"步骤 {type(step).__name__} 收到错误阶段 {context.stage}")
            result = step.process(context)
            if not isinstance(result, PreprocessContext):
                raise TypeError(f"步骤 {type(step).__name__} 必须返回 PreprocessContext")
            if result.stage != step.output_stage:
                raise TypeError(
                    f"步骤 {type(step).__name__} 输出阶段为 {result.stage}，"
                    f"声明为 {step.output_stage}"
                )
            context = result
        if context.document is None:
            raise TypeError("validated 阶段必须提供 ProcessedDocument")
        return context.document


class StructureStrategy(Protocol):
    def build(self, blocks: list[ContentBlock], raw: RawDocument) -> list[SemanticContext]: ...


class Parser(Protocol):
    def parse(self, raw: RawDocument) -> list[ContentBlock]: ...


class ParseStep:
    input_stage = "raw"
    output_stage = "blocks"

    def __init__(self, parser: Parser):
        self.parser = parser

    def process(self, context: PreprocessContext) -> PreprocessContext:
        context.blocks = self.parser.parse(context.raw)
        return _set_stage(context, self.output_stage)


class StructureStep:
    input_stage = "blocks"
    output_stage = "units"

    def __init__(self, strategy: StructureStrategy):
        self.strategy = strategy

    def process(self, context: PreprocessContext) -> PreprocessContext:
        context.units = self.strategy.build(context.blocks, context.raw)
        return _set_stage(context, self.output_stage)


class Chunker(Protocol):
    def chunk(self, units: list[SemanticContext]) -> list[SemanticContext]: ...


class ChunkStep:
    input_stage = "units"
    output_stage = "chunked"

    def __init__(self, chunker: Chunker):
        self.chunker = chunker

    def process(self, context: PreprocessContext) -> PreprocessContext:
        context.units = self.chunker.chunk(context.units)
        return _set_stage(context, self.output_stage)


class BuildDocumentStep:
    input_stage = "chunked"
    output_stage = "document"

    def __init__(self, *, document_schema: str, schema_version: int = 1):
        self.document_schema = document_schema
        self.schema_version = schema_version

    def process(self, context: PreprocessContext) -> PreprocessContext:
        metadata = context.raw.metadata
        title = str(metadata.get("title") or self._first_title(context) or "未命名文档")
        source_date = _source_date(metadata.get("source_date"))
        context.document = ProcessedDocument(
            title=title,
            document_schema=self.document_schema,
            schema_version=self.schema_version,
            source_date=source_date,
            metadata=dict(metadata.get("document_metadata", {})),
            warnings=list(context.warnings),
            contexts=[ContextDraft(
                key=unit.key, title=unit.title, body=unit.body,
                children=[EvidenceDraft(
                    key=child.key, body=child.body, locator=dict(child.locator),
                    metadata=dict(child.metadata), warnings=list(child.warnings),
                ) for child in unit.children],
                locator=dict(unit.locator), metadata=dict(unit.metadata), warnings=list(unit.warnings),
            ) for unit in context.units],
        )
        return _set_stage(context, self.output_stage)

    @staticmethod
    def _first_title(context: PreprocessContext) -> str | None:
        for block in context.blocks:
            if block.kind == "heading" and block.text.strip():
                return block.text.strip()
        return None


class ValidateStep:
    input_stage = "document"
    output_stage = "validated"

    def __init__(self, input_validator: Callable[[ProcessedDocument], None] | None = None):
        self.input_validator = input_validator

    def process(self, context: PreprocessContext) -> PreprocessContext:
        if context.document is None:
            raise TypeError("document 阶段缺少 ProcessedDocument")
        context.document = validate_document(context.document)
        if self.input_validator is not None:
            self.input_validator(context.document)
        return _set_stage(context, self.output_stage)


def _source_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError("source_date 必须是 ISO 日期") from None
    raise ValueError("source_date 必须是 date 或 ISO 日期")

