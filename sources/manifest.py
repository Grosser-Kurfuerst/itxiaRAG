"""人工导入清单：单篇优先，目录规则按最长前缀匹配；类别集合由各平台声明。"""
import tomllib
from dataclasses import dataclass
from pathlib import Path

from contracts.types import SourceRef


VISIBILITIES = {"public", "internal"}


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Classification:
    category: str | None
    decided_by: str
    skip: str | None = None


def valid_component(value):
    """集合、条目等标识会拼进文件路径与清单键，不能含路径分隔符或特殊目录名。"""
    return (isinstance(value, str) and bool(value.strip())
            and value not in {".", ".."} and not any(char in value for char in "/\\\x00"))


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
    def __init__(self, data, *, source_type: str, categories: set[str]):
        _table(data, {"version", "source_type", "connector", "collections", "path_rules", "docs"}, "清单")
        if type(data.get("version")) is not int or data["version"] != 2:
            raise ManifestError("version 必须是 2")
        if data.get("source_type") != source_type:
            raise ManifestError(f"source_type 必须是 {source_type}")
        self.source_type = source_type
        # connector 表交给对应平台命令解释，例如语雀的团队标识 group。
        self.connector = data.get("connector", {})
        if not isinstance(self.connector, dict):
            raise ManifestError("connector 必须是表")
        self._collections = data.get("collections")
        if not isinstance(self._collections, dict) or not self._collections:
            raise ManifestError("collections 必须登记至少一个集合")
        for collection, entry in self._collections.items():
            if not valid_component(collection):
                raise ManifestError(f"collections 集合标识非法：{collection}")
            _table(entry, {"visibility"}, f"collections.{collection}")
            _choice(entry.get("visibility"), VISIBILITIES, f"collections.{collection}.visibility")
        self.docs = data.get("docs", {})
        if not isinstance(self.docs, dict):
            raise ManifestError("docs 必须是表")
        for key, entry in self.docs.items():
            parts = key.split("/")
            if len(parts) != 2 or any(not valid_component(part) for part in parts):
                raise ManifestError(f"docs 文档键必须是集合/条目：{key}")
            if parts[0] not in self._collections:
                raise ManifestError(f"docs.{key} 的集合未登记")
            _table(entry, {"category", "skip", "canonical", "visibility", "metadata"}, f"docs.{key}")
            if ("category" in entry) == ("skip" in entry):
                raise ManifestError(f"docs.{key} 必须且只能指定 category 或 skip")
            if "category" in entry:
                _choice(entry["category"], categories, f"docs.{key}.category")
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
            if "metadata" in entry:
                metadata = entry["metadata"]
                if "category" not in entry or not isinstance(metadata, dict):
                    raise ManifestError(f"docs.{key}.metadata 只能用于 category 条目且必须是表")
                # 平台命名空间由连接器维护，清单只补充平台给不了的预处理字段。
                if source_type in metadata:
                    raise ManifestError(f"docs.{key}.metadata 不能覆盖平台字段 {source_type}")
        self.path_rules = data.get("path_rules", [])
        if not isinstance(self.path_rules, list):
            raise ManifestError("path_rules 必须是表数组")
        for index, rule in enumerate(self.path_rules):
            location = f"path_rules[{index}]"
            _table(rule, {"collection", "path_prefix", "category"}, location)
            if not isinstance(rule.get("collection"), str) or rule["collection"] not in self._collections:
                raise ManifestError(f"{location}.collection 必须是已登记的集合")
            prefix = rule.get("path_prefix")
            if (not isinstance(prefix, list) or not 1 <= len(prefix) <= 10
                    or any(not isinstance(part, str) or not part.strip() or len(part) > 100 for part in prefix)):
                raise ManifestError(f"{location}.path_prefix 必须是 1～10 项非空文本，每项最多 100 字")
            _choice(rule.get("category"), categories, f"{location}.category")
        prefixes = [(rule["collection"], tuple(rule["path_prefix"])) for rule in self.path_rules]
        if len(prefixes) != len(set(prefixes)):
            raise ManifestError("path_rules 不能重复登记同一集合的相同路径前缀")

    @classmethod
    def load(cls, path, *, source_type: str, categories: set[str]):
        try:
            with Path(path).open("rb") as stream:
                data = tomllib.load(stream)
        except (OSError, ValueError) as exc:
            raise ManifestError(f"无法读取导入清单：{exc}") from None
        return cls(data, source_type=source_type, categories=categories)

    @property
    def collections(self) -> list[str]:
        return list(self._collections)

    def classify(self, ref: SourceRef) -> Classification:
        entry = self.docs.get(ref.key)
        if entry is not None:
            return Classification(entry.get("category"), "manifest", entry.get("skip"))
        matches = [rule for rule in self.path_rules
                   if rule["collection"] == ref.collection
                   and ref.collection_path[:len(rule["path_prefix"])] == tuple(rule["path_prefix"])]
        if matches:
            rule = max(matches, key=lambda item: len(item["path_prefix"]))
            return Classification(rule["category"], "path_rule")
        return Classification(None, "none")

    def visibility_for(self, ref: SourceRef) -> str:
        entry = self.docs.get(ref.key, {})
        return entry.get("visibility", self._collections[ref.collection]["visibility"])

    def canonical_for(self, ref: SourceRef) -> str | None:
        return self.docs.get(ref.key, {}).get("canonical")

    def metadata_for(self, ref: SourceRef) -> dict:
        return dict(self.docs.get(ref.key, {}).get("metadata", {}))
