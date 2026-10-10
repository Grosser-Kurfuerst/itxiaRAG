"""关键词路的查询端同义扩展：问题含某组中的词组时，把同组其他词组追加到问题后。

只补充评测或真实提问中验证过的用词错配；文档端不扩展，向量路不使用。
"""
import functools
from pathlib import Path

_SYNONYMS = Path(__file__).with_name("keyword-synonyms.txt")


class SynonymExpander:
    def __init__(self, groups):
        self.groups = tuple(tuple(phrase.casefold() for phrase in group) for group in groups)
        for group in self.groups:
            if len(group) < 2 or any(len(phrase) < 2 for phrase in group):
                raise ValueError(f"同义词组至少两个词组，每个词组至少两个字：{group}")

    @classmethod
    def from_file(cls, path):
        """每行一组，词组以空白分隔；# 之后为注释。"""
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return cls(phrases for line in lines if (phrases := line.split("#", 1)[0].split()))

    def __call__(self, query: str) -> str:
        text = query.casefold()
        extra = [phrase for group in self.groups if any(phrase in text for phrase in group)
                 for phrase in group if phrase not in text]
        return " ".join([query, *dict.fromkeys(extra)])


@functools.cache
def default_expander() -> SynonymExpander:
    return SynonymExpander.from_file(_SYNONYMS)
