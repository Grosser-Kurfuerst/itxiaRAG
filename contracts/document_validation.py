from contracts.errors import DomainError
from contracts.types import ContextDraft, EvidenceDraft, ProcessedDocument


def validate_document(document, input):
    """当前 generic_note 的硬约束；不因可替换处理器省略产物检查。"""
    error = DomainError("CONTENT_SCHEMA_INVALID", "父子产物未通过完整性校验")
    if not isinstance(document, ProcessedDocument) or type(document.contexts) is not list or len(document.contexts) != 1:
        raise error
    parent = document.contexts[0]
    if (not isinstance(parent, ContextDraft) or type(parent.ordinal) is not int
            or parent.ordinal != 1 or parent.body != input.input_text or parent.title != input.title):
        raise error
    if parent.scope_fields != {} or parent.field_sources != [] or parent.knowledge_types != ["concept"]:
        raise error
    if type(parent.children) is not list or len(parent.children) != 1:
        raise error
    child = parent.children[0]
    if not isinstance(child, EvidenceDraft) or type(child.ordinal) is not int:
        raise error
    locator = {"content_hash": input.content_hash, "spans": [{
        "heading_path": [input.title], "line_start": 1,
        "line_end": len(input.input_text.split("\n")),
    }]}
    warnings = ["原始日期未知"] if input.source_date is None else []
    if (child.ordinal != 1 or child.body != input.input_text or child.knowledge_type != "concept"
            or child.evidence_role != "source_statement" or child.context_role != "main"
            or child.structured_fields != {"applicability": "unknown"}):
        raise error
    if (parent.locator != locator or child.locator != locator or parent.warnings != warnings
            or child.warnings != warnings or document.warnings != warnings):
        raise error
    return document
