"""组合根：更换适配器只修改这里，业务编排只依赖 contracts 中的协议。"""
from django.conf import settings

from catalog.selectors import DjangoContextReader
from catalog.storage import DjangoDocumentStore
from embeddings.openai_compatible import OpenAICompatibleEmbedding
from ingestion.registry import PreprocessorRegistry
from retrieval.hybrid import MultiRouteRecall
from retrieval.keyword import KeywordRetriever
from retrieval.pipeline import PostRecallPipeline
from retrieval.steps import GroupParentsStep, RRFFusionStep, TopKParentsStep
from retrieval.vector import VectorRetriever


def embedding_provider():
    return OpenAICompatibleEmbedding(**settings.EMBEDDING)


def document_store():
    return DjangoDocumentStore()


def context_reader():
    return DjangoContextReader()


def recall_collector(embedder):
    return MultiRouteRecall([
        KeywordRetriever(min_bm25=settings.RETRIEVAL_MIN_BM25),
        VectorRetriever(embedder, min_cosine=settings.RETRIEVAL_MIN_COSINE),
    ])


def post_recall_pipeline():
    # 插入、移除或调序兼容步骤只修改这里；默认不启用模型重排。
    return PostRecallPipeline([
        RRFFusionStep(settings.RETRIEVAL_RRF_K),
        GroupParentsStep(),
        TopKParentsStep(),
    ])


def preprocessors():
    # 后续在这里显式 register(schema, version, processor)，无需动态加载用户提供的代码。
    return PreprocessorRegistry()
