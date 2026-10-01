"""只负责装配；导入时不连接数据库和外部服务。"""
from ingestion.registry import parse_and_chunk


def document_builder():
    return parse_and_chunk
