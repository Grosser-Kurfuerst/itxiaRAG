import pytest

from contracts.types import RawDocument
from ingestion.preprocessing import (
    BuildDocumentStep,
    ChunkStep,
    ContentBlock,
    ParseStep,
    PreprocessContext,
    PreprocessPipeline,
    StructureStep,
    ValidateStep,
)


class Parser:
    def parse(self, raw):
        return [ContentBlock("paragraph", raw.content.decode(), ordinal=1)]


class Strategy:
    def build(self, blocks, raw):
        from ingestion.preprocessing import SemanticContext, SemanticEvidence

        body = blocks[0].text
        child = SemanticEvidence("detail", body)
        return [SemanticContext("doc", "测试文档", body, [child])]


class IdentityChunker:
    def chunk(self, units):
        return units


def pipeline(*steps):
    return PreprocessPipeline([
        ParseStep(Parser()), StructureStep(Strategy()), ChunkStep(IdentityChunker()),
        *steps, BuildDocumentStep(document_schema="test_note"), ValidateStep(),
    ])


def test_pipeline_runs_stages_and_returns_public_document():
    document = pipeline().process(RawDocument("正文".encode(), "text/plain", {"title": "标题"}))
    assert document.title == "标题"
    assert document.document_schema == "test_note"
    assert document.contexts[0].children[0].body == "正文"


def test_pipeline_rejects_incompatible_order_or_missing_terminal_step():
    with pytest.raises(ValueError, match="预期为 raw"):
        PreprocessPipeline([StructureStep(Strategy())])
    with pytest.raises(ValueError, match="validated"):
        PreprocessPipeline([ParseStep(Parser())])


def test_pipeline_rejects_step_that_does_not_set_declared_stage():
    class Broken(ParseStep):
        def process(self, context):
            return context

    with pytest.raises(TypeError, match="输出阶段"):
        PreprocessPipeline([
            Broken(Parser()), StructureStep(Strategy()), ChunkStep(IdentityChunker()),
            BuildDocumentStep(document_schema="test_note"), ValidateStep(),
        ]).process(RawDocument("正文".encode(), "text/plain"))


def test_custom_step_can_be_inserted_without_changing_pipeline_runner():
    class AddWarning:
        input_stage = output_stage = "chunked"

        def process(self, context: PreprocessContext):
            context.warnings.append("自定义步骤")
            context.stage = "chunked"
            return context

    document = pipeline(AddWarning()).process(RawDocument("正文".encode(), "text/plain"))
    assert document.warnings == ["自定义步骤"]


def test_compatible_steps_can_be_removed_and_reordered():
    class Prefix:
        input_stage = output_stage = "blocks"

        def process(self, context):
            from dataclasses import replace

            context.blocks = [replace(block, text="前缀 " + block.text) for block in context.blocks]
            return context

    class Truncate:
        input_stage = output_stage = "blocks"

        def process(self, context):
            from dataclasses import replace

            context.blocks = [replace(block, text=block.text[:2]) for block in context.blocks]
            return context

    def body(*extra):
        result = PreprocessPipeline([
            ParseStep(Parser()), *extra, StructureStep(Strategy()), ChunkStep(IdentityChunker()),
            BuildDocumentStep(document_schema="test_note"), ValidateStep(),
        ]).process(RawDocument("正文内容".encode(), "text/plain"))
        return result.contexts[0].body

    assert body() == "正文内容"
    assert body(Prefix(), Truncate()) == "前缀"
    assert body(Truncate(), Prefix()) == "前缀 正文"


def test_bad_output_and_step_failure_are_not_silenced():
    class BadOutput:
        input_stage = "raw"
        output_stage = "validated"

        def process(self, context):
            return None

    with pytest.raises(TypeError, match="PreprocessContext"):
        PreprocessPipeline([BadOutput()]).process(RawDocument(b"x", "text/plain"))

    class Failed(BadOutput):
        def process(self, context):
            raise RuntimeError("解析失败")

    with pytest.raises(RuntimeError, match="解析失败"):
        PreprocessPipeline([Failed()]).process(RawDocument(b"x", "text/plain"))

