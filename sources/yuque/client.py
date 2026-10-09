"""语雀 OpenAPI 与离线快照读取；不依赖数据库或模型服务。"""
import json
import time
from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPException
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from contracts.errors import DomainError, SourceAccessError
from sources.manifest import valid_component


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


def _items(payload):
    if (not isinstance(payload, dict) or not isinstance(payload.get("data"), list)
            or any(not isinstance(item, dict) for item in payload["data"])):
        raise ValueError
    return payload["data"]


def _doc_refs(book, toc, docs):
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


class YuqueAuthenticationError(SourceAccessError):
    """与单篇 DomainError 分开，防止导入服务吞掉整批认证失败。"""

    def __init__(self):
        super().__init__("语雀认证或授权失败，请检查 YUQUE_TOKEN 与知识库权限")


class YuqueOpenApiClient:
    def __init__(self, base_url, token, group, *, interval=0.5, timeout=30):
        if not token or not token.strip():
            raise DomainError("YUQUE_NOT_CONFIGURED", "请配置环境变量 YUQUE_TOKEN")
        if not base_url or not valid_component(group):
            raise DomainError("YUQUE_NOT_CONFIGURED", "请检查 YUQUE_API_BASE 与团队标识")
        self.base_url, self.token, self.group = base_url.rstrip("/"), token, group
        self.interval, self.timeout = interval, timeout
        self._last_request_at = None
        self._metadata = {}

    def _get(self, path):
        if self._last_request_at is not None:
            delay = self.interval - (time.monotonic() - self._last_request_at)
            if delay > 0:
                time.sleep(delay)
        try:
            request = Request(self.base_url + path, headers={
                "X-Auth-Token": self.token,
                "User-Agent": "itxiaRAG/yuque-ingestion",
                "Accept": "application/json",
            })
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status in {401, 403}:
                raise YuqueAuthenticationError() from None
            if status == 429:
                raise DomainError("YUQUE_RATE_LIMITED", "语雀请求限流，请稍后重跑", 429) from None
            raise DomainError("YUQUE_UNAVAILABLE", f"语雀接口返回 HTTP {status}", 502) from None
        except (URLError, TimeoutError, OSError, HTTPException):
            raise DomainError("YUQUE_UNAVAILABLE", "语雀接口调用失败或超时", 502) from None
        except (ValueError, UnicodeError):
            raise DomainError("INVALID_YUQUE_RESPONSE", "语雀接口返回格式错误", 502) from None
        finally:
            self._last_request_at = time.monotonic()

    def _repo_path(self, book):
        if not valid_component(book):
            raise DomainError("INVALID_YUQUE_RESPONSE", "语雀知识库标识非法")
        return f"/repos/{quote(self.group, safe='')}/{quote(book, safe='')}"

    def list_docs(self, book: str) -> list[YuqueDocRef]:
        path = self._repo_path(book)
        try:
            toc = _items(self._get(path + "/toc"))
            docs, offset = [], 0
            while True:
                page = _items(self._get(path + "/docs?" + urlencode({"offset": offset, "limit": 100})))
                docs.extend(page)
                if len(page) < 100:
                    break
                offset += len(page)
            refs = _doc_refs(book, toc, docs)
        except (KeyError, TypeError, ValueError):
            raise DomainError("INVALID_YUQUE_RESPONSE", "语雀目录或文档列表格式错误", 502) from None
        self._metadata[book] = (toc, docs)
        return refs

    def read_markdown(self, ref: YuqueDocRef) -> str:
        if not valid_component(ref.slug):
            raise DomainError("INVALID_YUQUE_RESPONSE", "语雀文档 slug 非法")
        payload = self._get(self._repo_path(ref.book) + "/docs/" + quote(ref.slug, safe=""))
        try:
            body = payload["data"]["body"]
            if not isinstance(body, str):
                raise ValueError
            return body
        except (KeyError, TypeError, ValueError):
            raise DomainError("INVALID_YUQUE_RESPONSE", "语雀文档缺少 Markdown body", 502) from None

    def save_snapshot(self, directory, refs):
        """保存已列出的元数据与指定正文；读取失败供导入报告使用。"""
        directory, errors = Path(directory), {}
        try:
            for book, (toc, docs) in self._metadata.items():
                target = directory / book
                target.mkdir(parents=True, exist_ok=True)
                for filename, items in [("toc.json", toc), ("docs.json", docs)]:
                    (target / filename).write_text(json.dumps({"data": items}, ensure_ascii=False), encoding="utf-8")
            for ref in refs:
                target = directory / ref.book / f"{ref.slug}.md"
                try:
                    body = self.read_markdown(ref)
                except DomainError as exc:
                    # 重跑保存失败时不能留下旧正文，被误当作本次成功快照。
                    target.unlink(missing_ok=True)
                    errors[f"{ref.book}/{ref.slug}"] = exc
                    continue
                target.write_text(body, encoding="utf-8")
        except (OSError, UnicodeError):
            raise DomainError("SNAPSHOT_WRITE_FAILED", "无法写入语雀快照，请检查目录与文件权限") from None
        return errors


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
            return _items(json.loads(self._read(book, filename)))
        except ValueError:
            raise DomainError("INVALID_SNAPSHOT", f"{book}/{filename} 必须是含 data 数组的 OpenAPI 响应") from None

    def list_docs(self, book: str) -> list[YuqueDocRef]:
        toc = self._items(book, "toc.json")
        docs = self._items(book, "docs.json")
        try:
            return _doc_refs(book, toc, docs)
        except (KeyError, TypeError, ValueError):
            raise DomainError("INVALID_SNAPSHOT", f"{book} 的目录或文档元数据非法，请检查身份、目录父节点和更新时间") from None

    def read_markdown(self, ref: YuqueDocRef) -> str:
        if not valid_component(ref.slug):
            raise DomainError("INVALID_SNAPSHOT", "快照文档 slug 非法")
        return self._read(ref.book, f"{ref.slug}.md")
