"""组合根：更换适配器只修改这里，业务编排只依赖 contracts 中的协议。"""
from django.conf import settings

from catalog.selectors import DjangoContextReader
from catalog.storage import DjangoDocumentStore
from embeddings.openai_compatible import OpenAICompatibleEmbedding
from ingestion.registry import PreprocessorRegistry
from retrieval.hybrid import HybridRetriever, RRFRanker
from retrieval.keyword import KeywordRetriever
from retrieval.vector import VectorRetriever


def embedding_provider():
    return OpenAICompatibleEmbedding(**settings.EMBEDDING)


def document_store():
    return DjangoDocumentStore()


def context_reader():
    return DjangoContextReader()


def retriever(embedder):
    return HybridRetriever([KeywordRetriever(), VectorRetriever(embedder)],
                           RRFRanker(settings.RETRIEVAL_RRF_K))


def preprocessors():
    # 后续在这里显式 register(schema, version, processor)，无需动态加载用户提供的代码。
    return PreprocessorRegistry()
