"""关键词路的公共分析器：中文分词，型号和错误码保持完整。"""
import functools
import re
from pathlib import Path

import jieba


_PARTS = re.compile(r"[A-Za-z0-9]+(?:[._%+#/-][A-Za-z0-9]+)*(?:\+\+|[%+#])?|[㐀-䶿一-鿿]+")
# 型号的字母段与数字段：air14 → air、14；tb14+ → tb、14+，与正文“ThinkBook 14+”的切法对齐。
_PIECES = re.compile(r"[a-z]+|\d+(?:\.\d+)*\+?")
_STOPWORDS = frozenset("的 了 吗 呢 啊 是 有 这 那 这个 那个 这台 那台 台 怎么 怎么样 如何 能 用 多久 很 我 你".split())
_TERMS = Path(__file__).with_name("keyword-terms.txt")


@functools.cache
def _segmenter() -> jieba.Tokenizer:
    # 独立实例，不改动全局 jieba 词典；首次分词时才加载。
    segmenter = jieba.Tokenizer()
    for line in _TERMS.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            segmenter.add_word(word)
    return segmenter


def _ascii_tokens(part: str) -> list[str]:
    # 保留完整型号，并补充字母段／数字段；单字符片段（如 i7 的 i）区分度过低，不补充。
    pieces = _PIECES.findall(part)
    if len(pieces) < 2:
        return [part]
    return [part, *(piece for piece in pieces if len(piece) > 1)]


def tokenize(text: str, *, search_mode: bool = False) -> list[str]:
    """文档和查询复用；保留重复词供 BM25 统计词频，不做查询改写。

    search_mode 使用 jieba 搜索模式：长词之外再补其中的两字、三字词，
    如“数据恢复”另产生“数据”“恢复”，使问题与原文的复合词能互相匹配。
    """
    cut = _segmenter().lcut_for_search if search_mode else _segmenter().lcut
    tokens = []
    for part in _PARTS.findall(text.casefold()):
        words = _ascii_tokens(part) if part.isascii() else cut(part, HMM=False)
        tokens.extend(word for word in words if word not in _STOPWORDS)
    return tokens


def tokenize_for_search(text: str) -> list[str]:
    return tokenize(text, search_mode=True)
