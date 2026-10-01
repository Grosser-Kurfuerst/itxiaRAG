import hashlib
import json


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_digest(data):
    keys = ("input_text", "title", "author", "source_date", "document_schema",
            "schema_version", "source_metadata", "domain_metadata")
    payload = {key: data[key] for key in keys}
    if payload["source_date"] is not None:
        payload["source_date"] = payload["source_date"].isoformat()
    return digest(payload)
