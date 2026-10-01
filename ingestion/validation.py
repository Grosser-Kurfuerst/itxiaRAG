"""兼容导入模块入口；纯产物契约同时用于发布前校验。"""
from contracts.document_validation import validate_document

__all__ = ["validate_document"]
