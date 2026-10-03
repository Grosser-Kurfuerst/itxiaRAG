"""关键词路的公共分析器：中文分词，型号和错误码保持完整。"""
import re

import jieba


_PARTS = re.compile(r"[A-Za-z0-9]+(?:[._%+#/-][A-Za-z0-9]+)*(?:\+\+|[%+#])?|[\u3400-\u4dbf\u4e00-\u9fff]+")
_STOPWORDS = frozenset("的 了 吗 呢 啊 是 有 这 那 这个 那个 这台 那台 台 怎么 怎么样 如何 能 用 多久 很 我 你".split())


def tokenize(text: str) -> list[str]:
    """文档和查询复用；保留重复词供 BM25 统计词频，不做查询改写。"""
    tokens = []
    for part in _PARTS.findall(text.casefold()):
        words = [part] if part.isascii() else jieba.lcut(part, HMM=False)
        tokens.extend(word for word in words if word not in _STOPWORDS)
    return tokens
