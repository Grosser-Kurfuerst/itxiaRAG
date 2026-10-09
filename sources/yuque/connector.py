"""把语雀客户端适配为 SourceConnector：身份、链接、标题清洗与平台元数据在此生成。"""
import re
from zoneinfo import ZoneInfo

from contracts.types import FetchedSource, RawDocument, SourceRef
from sources.yuque.client import YuqueClient, YuqueDocRef


CATEGORIES = {"tutorial", "tool_card", "knowledge", "troubleshooting", "case"}


def clean_title(title: str) -> str:
    title = re.sub(r"^(?:【[^】]*】\s*)+", "", title.strip())
    title = re.sub(r"^[^|｜]{0,20}[|｜]\s*", "", title)
    return re.sub(r"[\s⭐]+$", "", title).strip()


def to_source_ref(doc: YuqueDocRef) -> SourceRef:
    return SourceRef(
        collection=doc.book, key=f"{doc.book}/{doc.slug}", canonical_locator=f"doc:{doc.doc_id}",
        title=clean_title(doc.title), collection_path=doc.toc_path, updated_at=doc.content_updated_at,
        extra={"doc_id": doc.doc_id, "book": doc.book, "slug": doc.slug, "title_raw": doc.title},
    )


def to_doc_ref(ref: SourceRef) -> YuqueDocRef:
    extra = ref.extra
    return YuqueDocRef(extra["doc_id"], extra["book"], extra["slug"], extra["title_raw"],
                       ref.collection_path, ref.updated_at)


class YuqueConnector:
    source_type = "yuque"

    def __init__(self, client: YuqueClient, group: str, books: list[str]):
        self.client, self.group, self.books = client, group, books

    def list(self) -> list[SourceRef]:
        return [to_source_ref(doc) for book in self.books for doc in self.client.list_docs(book)]

    def fetch(self, ref: SourceRef) -> FetchedSource:
        doc = to_doc_ref(ref)
        markdown = self.client.read_markdown(doc)
        metadata = {
            "title": ref.title,
            "source_date": doc.content_updated_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            "collection_path": list(doc.toc_path),
            "yuque": {
                "doc_id": doc.doc_id, "book": doc.book, "slug": doc.slug,
                "title_raw": doc.title, "content_updated_at": doc.content_updated_at.isoformat(),
            },
        }
        return FetchedSource(
            ref, RawDocument(markdown.encode("utf-8"), "text/x-yuque-markdown", metadata),
            f"https://www.yuque.com/{self.group}/{doc.book}/{doc.slug}",
        )
