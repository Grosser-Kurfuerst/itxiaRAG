"""人工导入清单：单篇优先，目录规则按最长前缀匹配。"""
import tomllib
from dataclasses import dataclass
from pathlib import Path

from sources.yuque.client import YuqueDocRef, valid_component


CATEGORIES = {"tutorial", "tool_card", "knowledge", "troubleshooting", "case"}
VISIBILITIES = {"public", "internal"}


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Classification:
    category: str | None
    decided_by: str
    skip: str | None = None


def _table(value, allowed, location):
    if not isinstance(value, dict):
        raise ManifestError(f"{location} 必须是表")
    unknown = set(value) - allowed
    if unknown:
        raise ManifestError(f"{location} 未知字段：{', '.join(sorted(unknown))}")


def _choice(value, choices, location):
    if not isinstance(value, str) or value not in choices:
        raise ManifestError(f"{location} 非法值，可选：{', '.join(sorted(choices))}")


class Manifest:
    def __init__(self, data):
        _table(data, {"version", "group", "books", "path_rules", "docs"}, "清单")
        if type(data.get("version")) is not int or data["version"] != 1:
            raise ManifestError("version 必须是 1")
        if not valid_component(data.get("group")):
            raise ManifestError("group 必须是非空的团队标识")
        self.group = data["group"]
        self._books = data.get("books")
        if not isinstance(self._books, dict) or not self._books:
            raise ManifestError("books 必须登记至少一个知识库")
        for book, entry in self._books.items():
            if not valid_component(book):
                raise ManifestError(f"books 知识库标识非法：{book}")
            _table(entry, {"visibility"}, f"books.{book}")
            _choice(entry.get("visibility"), VISIBILITIES, f"books.{book}.visibility")
        self.docs = data.get("docs", {})
        if not isinstance(self.docs, dict):
            raise ManifestError("docs 必须是表")
        for key, entry in self.docs.items():
            parts = key.split("/")
            if len(parts) != 2 or any(not valid_component(part) for part in parts):
                raise ManifestError(f"docs 文档键必须是知识库/slug：{key}")
            if parts[0] not in self._books:
                raise ManifestError(f"docs.{key} 的知识库未登记")
            _table(entry, {"category", "skip", "canonical", "visibility"}, f"docs.{key}")
            if ("category" in entry) == ("skip" in entry):
                raise ManifestError(f"docs.{key} 必须且只能指定 category 或 skip")
            if "category" in entry:
                _choice(entry["category"], CATEGORIES, f"docs.{key}.category")
            if "skip" in entry and (not isinstance(entry["skip"], str) or not entry["skip"].strip()):
                raise ManifestError(f"docs.{key}.skip 必须是非空原因")
            if "visibility" in entry:
                _choice(entry["visibility"], VISIBILITIES, f"docs.{key}.visibility")
            if "canonical" in entry:
                if "skip" not in entry:
                    raise ManifestError(f"docs.{key}.canonical 只能用于 skip 条目")
                target = entry["canonical"]
                if not isinstance(target, str) or target not in self.docs:
                    raise ManifestError(f"docs.{key}.canonical 指向不存在的条目")
        self.path_rules = data.get("path_rules", [])
        if not isinstance(self.path_rules, list):
            raise ManifestError("path_rules 必须是表数组")
        for index, rule in enumerate(self.path_rules):
            location = f"path_rules[{index}]"
            _table(rule, {"book", "path_prefix", "category"}, location)
            if not isinstance(rule.get("book"), str) or rule["book"] not in self._books:
                raise ManifestError(f"{location}.book 必须是已登记的知识库")
            prefix = rule.get("path_prefix")
            if (not isinstance(prefix, list) or not 1 <= len(prefix) <= 10
                    or any(not isinstance(part, str) or not part.strip() or len(part) > 100 for part in prefix)):
                raise ManifestError(f"{location}.path_prefix 必须是 1～10 项非空文本，每项最多 100 字")
            _choice(rule.get("category"), CATEGORIES, f"{location}.category")
        prefixes = [(rule["book"], tuple(rule["path_prefix"])) for rule in self.path_rules]
        if len(prefixes) != len(set(prefixes)):
            raise ManifestError("path_rules 不能重复登记同一知识库的相同路径前缀")

    @classmethod
    def load(cls, path):
        try:
            with Path(path).open("rb") as stream:
                data = tomllib.load(stream)
        except (OSError, ValueError) as exc:
            raise ManifestError(f"无法读取导入清单：{exc}") from None
        return cls(data)

    @property
    def books(self) -> list[str]:
        return list(self._books)

    def classify(self, ref: YuqueDocRef) -> Classification:
        entry = self.docs.get(f"{ref.book}/{ref.slug}")
        if entry is not None:
            return Classification(entry.get("category"), "manifest", entry.get("skip"))
        matches = [rule for rule in self.path_rules
                   if rule["book"] == ref.book
                   and ref.toc_path[:len(rule["path_prefix"])] == tuple(rule["path_prefix"])]
        if matches:
            rule = max(matches, key=lambda item: len(item["path_prefix"]))
            return Classification(rule["category"], "path_rule")
        return Classification(None, "none")

    def visibility_for(self, ref: YuqueDocRef) -> str:
        entry = self.docs.get(f"{ref.book}/{ref.slug}", {})
        return entry.get("visibility", self._books[ref.book]["visibility"])

    def canonical_for(self, ref: YuqueDocRef) -> str | None:
        return self.docs.get(f"{ref.book}/{ref.slug}", {}).get("canonical")
