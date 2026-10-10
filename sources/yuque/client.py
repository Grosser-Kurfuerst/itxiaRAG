"""语雀公开网页与离线快照读取；不依赖数据库或模型服务。"""
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPException
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode
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


class YuqueAccessDeniedError(SourceAccessError):
    """与单篇 DomainError 分开，防止导入服务吞掉整批访问拒绝。"""

    def __init__(self):
        super().__init__("语雀拒绝匿名访问，请确认知识库公开，或稍后重跑")


_APP_DATA = re.compile(r'window\.appData = JSON\.parse\(decodeURIComponent\("([^"]+)"\)\)')
_MARKDOWN_EXPORT = urlencode({"attachment": "true", "latexcode": "false", "anchor": "false", "linebreak": "false"})


def _book_from_page(html):
    """知识库页面内嵌的 appData 含知识库 ID 与目录。"""
    match = _APP_DATA.search(html)
    if not match:
        raise ValueError
    book = json.loads(unquote(match.group(1)))["book"]
    if type(book["id"]) is not int or not isinstance(book["toc"], list):
        raise ValueError
    return book["id"], book["toc"]


class YuqueWebClient:
    """匿名读取语雀网页端的公开知识库：目录取自知识库页面，正文为网页 Markdown 导出。"""

    def __init__(self, group, *, base_url="https://www.yuque.com", interval=1, timeout=30):
        self.base_url, self.group = base_url.rstrip("/"), group
        self.interval, self.timeout = interval, timeout
        self._last_request_at = None
        self._metadata = {}

    def _get(self, path, content_type):
        """返回响应文本；类型不符通常是验证码或登录页，按格式错误处理。"""
        if self._last_request_at is not None:
            delay = self.interval - (time.monotonic() - self._last_request_at)
            if delay > 0:
                time.sleep(delay)
        try:
            request = Request(self.base_url + path, headers={
                "User-Agent": "itxiaRAG/yuque-ingestion",
                "Accept": content_type,
            })
            with urlopen(request, timeout=self.timeout) as response:
                if response.headers.get_content_type() != content_type:
                    raise ValueError
                return response.read().decode("utf-8")
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status in {401, 403}:
                raise YuqueAccessDeniedError() from None
            if status == 429:
                raise DomainError("YUQUE_RATE_LIMITED", "语雀请求限流，请稍后重跑", 429) from None
            raise DomainError("YUQUE_UNAVAILABLE", f"语雀接口返回 HTTP {status}", 502) from None
        except (URLError, TimeoutError, OSError, HTTPException):
            raise DomainError("YUQUE_UNAVAILABLE", "语雀接口调用失败或超时", 502) from None
        except (ValueError, UnicodeError):
            raise DomainError("INVALID_YUQUE_RESPONSE", "语雀接口返回格式错误", 502) from None
        finally:
            self._last_request_at = time.monotonic()

    def _book_path(self, book):
        if not valid_component(book):
            raise DomainError("INVALID_YUQUE_RESPONSE", "语雀知识库标识非法")
        return f"/{quote(self.group, safe='')}/{quote(book, safe='')}"

    def list_docs(self, book: str) -> list[YuqueDocRef]:
        page = self._get(self._book_path(book), "text/html")
        try:
            book_id, toc = _book_from_page(page)
            docs, offset = [], 0
            while True:
                query = urlencode({"book_id": book_id, "offset": offset, "limit": 100})
                batch = _items(json.loads(self._get("/api/docs?" + query, "application/json")))
                docs.extend(batch)
                if len(batch) < 100:
                    break
                offset += len(batch)
            refs = _doc_refs(book, toc, docs)
        except (KeyError, TypeError, ValueError):
            raise DomainError("INVALID_YUQUE_RESPONSE", "语雀目录或文档列表格式错误", 502) from None
        self._metadata[book] = (toc, docs)
        return refs

    def read_markdown(self, ref: YuqueDocRef) -> str:
        if not valid_component(ref.slug):
            raise DomainError("INVALID_YUQUE_RESPONSE", "语雀文档 slug 非法")
        path = f"{self._book_path(ref.book)}/{quote(ref.slug, safe='')}/markdown?{_MARKDOWN_EXPORT}"
        return self._get(path, "text/markdown")

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
            raise DomainError("INVALID_SNAPSHOT", f"{book}/{filename} 必须是含 data 数组的 JSON") from None

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
