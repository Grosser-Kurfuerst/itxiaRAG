"""语雀文档引用与离线快照读取；不依赖数据库或模型服务。"""
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from contracts.errors import DomainError


@dataclass(frozen=True)
class YuqueDocRef:
    doc_id: int
    book: str
    slug: str
    title: str
    toc_path: tuple[str, ...]
    content_updated_at: datetime


class YuqueClient(Protocol):
    def list_docs(self, book: str) -> list[YuqueDocRef]: ...
    def read_markdown(self, ref: YuqueDocRef) -> str: ...


def valid_component(value):
    return (isinstance(value, str) and bool(value.strip())
            and value not in {".", ".."} and not any(char in value for char in "/\\\x00"))


class YuqueSnapshotClient:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _read(self, book, filename):
        if not valid_component(book):
            raise DomainError("INVALID_SNAPSHOT", "快照知识库标识非法")
        path = self.directory / book / filename
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise DomainError("SNAPSHOT_READ_FAILED", f"无法读取快照文件：{path}") from None

    def _items(self, book, filename):
        try:
            payload = json.loads(self._read(book, filename))
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError
            if any(not isinstance(item, dict) for item in payload["data"]):
                raise ValueError
            return payload["data"]
        except ValueError:
            raise DomainError("INVALID_SNAPSHOT", f"{book}/{filename} 必须是含 data 数组的 OpenAPI 响应") from None

    def list_docs(self, book: str) -> list[YuqueDocRef]:
        toc = self._items(book, "toc.json")
        docs = self._items(book, "docs.json")
        try:
            nodes = {node["uuid"]: node for node in toc}
            by_id = {node["doc_id"]: node for node in toc if node["type"] == "DOC"}
            by_slug = {node["url"]: node for node in toc if node["type"] == "DOC"}
            refs = []
            for doc in docs:
                if (type(doc["id"]) is not int or doc["id"] < 1 or not valid_component(doc["slug"])
                        or not isinstance(doc["title"], str) or not doc["title"].strip()):
                    raise ValueError
                updated = datetime.fromisoformat(doc["content_updated_at"])
                if updated.tzinfo is None:
                    raise ValueError
                node = by_id.get(doc["id"], by_slug.get(doc["slug"]))
                path, visited = [], set()
                parent = node.get("parent_uuid") if node else None
                while parent:
                    if parent in visited:
                        raise ValueError
                    visited.add(parent)
                    ancestor = nodes[parent]
                    path.append(ancestor["title"])
                    parent = ancestor.get("parent_uuid")
                refs.append(YuqueDocRef(doc["id"], book, doc["slug"], doc["title"],
                                        tuple(reversed(path)), updated))
            return refs
        except (KeyError, TypeError, ValueError):
            raise DomainError("INVALID_SNAPSHOT", f"{book} 的目录或文档元数据非法，请检查身份、目录父节点和更新时间") from None

    def read_markdown(self, ref: YuqueDocRef) -> str:
        if not valid_component(ref.slug):
            raise DomainError("INVALID_SNAPSHOT", "快照文档 slug 非法")
        return self._read(ref.book, f"{ref.slug}.md")
