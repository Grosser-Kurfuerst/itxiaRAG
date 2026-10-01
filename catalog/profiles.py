"""配置输入校验与运行快照验证；不在模块导入时读取文件或数据库。"""
import json
from pathlib import Path

from catalog.hashes import canonical_json, digest
from contracts.errors import DomainError


def invalid_profile():
    return DomainError("PROFILE_INVALID", "配置缺失、损坏或不受当前版本支持", 503)


def exact_keys(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise invalid_profile()


def fixed(value, expected):
    if canonical_json(value) != canonical_json(expected):
        raise invalid_profile()


def bounded(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise invalid_profile()


def validate_index(profile):
    exact_keys(profile, ["schema_version", "document_processing", "normalization_version", "max_body_chars", "max_body_lines", "context_schema_version", "evidence_schema_version", "retrieval_text_template_version", "lexical_backend", "tokenizer", "embedding"])
    for key in ("schema_version", "normalization_version", "context_schema_version", "evidence_schema_version", "retrieval_text_template_version"):
        fixed(profile[key], 1)
    fixed(profile["max_body_chars"], 8000)
    fixed(profile["max_body_lines"], 200)
    fixed(profile["lexical_backend"], "postgres-keyword-v1")
    fixed(profile["tokenizer"], None)
    fixed(profile["embedding"], None)
    fixed(profile["document_processing"], {
        "format_parsers": {name: {"id": "plain-text", "version": "1.0.0"} for name in ("txt", "markdown")},
        "schema_processors": {"generic_note.v1": {"id": "generic-note", "version": "1.0.0"}},
    })
    return profile


def validate_query(profile, index_hash):
    exact_keys(profile, ["schema_version", "index_profile_hash", "query_processing", "keyword", "response_context_bytes", "default_top_k", "max_top_k", "embedding", "rrf", "reranker"])
    fixed(profile["schema_version"], 1)
    fixed(profile["index_profile_hash"], index_hash)
    exact_keys(profile["query_processing"], ["processor_id", "timeout_ms"])
    fixed(profile["query_processing"]["processor_id"], "noop-v1")
    bounded(profile["query_processing"]["timeout_ms"], 1, 1000)
    fixed(profile["keyword"], {"tokenizer_version": 1, "scorer_version": 1, "candidate_limit": 100, "max_terms": 16})
    bounded(profile["response_context_bytes"], 1, 65536)
    fixed(profile["max_top_k"], 20)
    bounded(profile["default_top_k"], 1, 20)
    for key in ("embedding", "rrf", "reranker"):
        fixed(profile[key], None)
    return profile


def load_profiles(directory):
    try:
        directory = Path(directory)
        index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
        query = json.loads((directory / "query.json").read_text(encoding="utf-8"))
        validate_index(index)
        index_hash = digest(index)
        if type(query) is not dict:
            raise invalid_profile()
        query.setdefault("index_profile_hash", index_hash)
        validate_query(query, index_hash)
        return dict(index_profile=index, index_profile_hash=index_hash,
                    query_profile=query, query_profile_hash=digest(query))
    except (OSError, ValueError, TypeError, KeyError):
        raise invalid_profile() from None


def active_profiles():
    from catalog.models import RetrievalSettings
    try:
        obj = RetrievalSettings.objects.get(pk=1)
        validate_index(obj.index_profile)
        if digest(obj.index_profile) != obj.index_profile_hash:
            raise invalid_profile()
        validate_query(obj.query_profile, obj.index_profile_hash)
        if digest(obj.query_profile) != obj.query_profile_hash:
            raise invalid_profile()
        return obj
    except (RetrievalSettings.DoesNotExist, ValueError, TypeError, KeyError):
        raise invalid_profile() from None
