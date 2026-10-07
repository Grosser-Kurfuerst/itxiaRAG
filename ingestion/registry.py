"""显式注册的处理器表；通过统一 DTO 校验，不自动识别文章类型。"""
from contracts.errors import DomainError
from contracts.serializers import validate_document
from contracts.types import DocumentPreprocessor, RawDocument, ProcessedDocument


class PreprocessorRegistry:
    def __init__(self):
        self._processors: dict[tuple[str, int], DocumentPreprocessor] = {}

    def register(self, schema: str, version: int, processor: DocumentPreprocessor):
        key = (schema, version)
        if key in self._processors:
            raise ValueError(f"处理器已注册: {key}")
        self._processors[key] = processor

    def process(self, raw: RawDocument, schema: str, version: int) -> ProcessedDocument:
        processor = self._processors.get((schema, version))
        if processor is None:
            raise DomainError("PREPROCESSOR_NOT_REGISTERED", "尚未接入该文档类型的预处理插件")
        document = validate_document(processor.process(raw))
        if (document.document_schema, document.schema_version) != (schema, version):
            raise DomainError("SCHEMA_MISMATCH", "插件输出与注册的文档类型不符")
        return document
