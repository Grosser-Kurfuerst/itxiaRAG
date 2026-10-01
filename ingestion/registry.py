from contracts.errors import DomainError
from contracts.types import DocumentProcessContext
from ingestion.parsers import PlainTextParser
from ingestion.processors import GenericNoteProcessor

PARSERS = {("plain-text", "1.0.0"): PlainTextParser}
PROCESSORS = {("generic-note", "1.0.0"): GenericNoteProcessor}


def parse_and_chunk(input, profile):
    try:
        mapping = profile["document_processing"]
        parser = mapping["format_parsers"][input.format]
        processor = mapping["schema_processors"][f"{input.document_schema}.v{input.schema_version}"]
        parser_cls = PARSERS[(parser["id"], parser["version"])]
        processor_cls = PROCESSORS[(processor["id"], processor["version"])]
    except (KeyError, TypeError):
        raise DomainError("IMPORT_CONFIGURATION_ERROR", "指定解析器或处理器未注册") from None
    parsed = parser_cls().parse(input)
    return processor_cls().process(parsed, DocumentProcessContext(input, profile))
