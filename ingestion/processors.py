from contracts.types import ContextDraft, EvidenceDraft, ProcessedDocument


class GenericNoteProcessor:
    def process(self, document, context):
        input = context.input
        block = document.blocks[0]
        locator = {"content_hash": input.content_hash, "spans": [{
            "heading_path": block.heading_path,
            "line_start": block.line_start, "line_end": block.line_end,
        }]}
        warnings = ["原始日期未知"] if input.source_date is None else []
        child = EvidenceDraft(1, block.text, "concept", "source_statement", "main",
                              locator, {"applicability": "unknown"}, warnings)
        parent = ContextDraft(1, input.title, block.text, {}, [], locator,
                              ["concept"], warnings, [child])
        return ProcessedDocument([parent], warnings)
