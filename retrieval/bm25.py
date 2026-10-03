"""小语料的纯 Python BM25；不维护持久索引或进程缓存。"""
from collections import Counter
from math import log1p


def bm25_scores(corpus: list[list[str]], query: list[str], k1=1.5, b=0.75) -> list[float]:
    frequencies = [Counter(tokens) for tokens in corpus]
    lengths = [sum(counts.values()) for counts in frequencies]
    size, total_length = len(corpus), sum(lengths)
    if not size or not total_length:
        return [0.0] * size
    average_length = total_length / size
    document_frequency = Counter(term for counts in frequencies for term in counts)
    # 正值 IDF 使单篇语料、常见词仍能召回；查询重复词只计算一次。
    idf = {term: log1p((size - document_frequency[term] + 0.5)
                      / (document_frequency[term] + 0.5)) for term in dict.fromkeys(query)}
    scores = []
    for counts, length in zip(frequencies, lengths):
        norm = k1 * (1 - b + b * length / average_length)
        scores.append(sum(weight * counts[term] * (k1 + 1) / (counts[term] + norm)
                          for term, weight in idf.items() if counts[term]))
    return scores
