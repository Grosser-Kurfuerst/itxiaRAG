"""组合根：更换适配器只修改这里，业务编排只依赖 contracts 中的协议。"""
from django.conf import settings

from catalog.selectors import DjangoContextReader
from catalog.storage import DjangoDocumentStore
from embeddings.openai_compatible import OpenAICompatibleEmbedding
from ingestion.registry import PreprocessorRegistry
from ingestion.chunking import BudgetChunker
from ingestion.enrichment import (
    CalloutWarningStep, RetrievalPrefixStep, SourceDateNoticeStep, TimeExpressionStep, ToolIdentityStep,
)
from ingestion.parsers import ParserRegistry
from ingestion.preprocessing import BuildDocumentStep, ChunkStep, ParseStep, PreprocessPipeline, StructureStep, ValidateStep
from ingestion.strategies import ExperienceCaseStrategy, PurchaseGuideStrategy, ReviewStrategy
from ingestion.sections import KNOWLEDGE, SectionedDocumentStrategy, ToolCardStrategy, TUTORIAL
from ingestion.yuque_markdown import YuqueMarkdownParser
from retrieval.hybrid import MultiRouteRecall
from retrieval.keyword import KeywordRetriever
from retrieval.pipeline import PostRecallPipeline
from retrieval.steps import GroupParentsStep, RRFFusionStep, TopKParentsStep
from retrieval.synonyms import default_expander
from retrieval.tokenization import tokenize, tokenize_for_search
from retrieval.vector import VectorRetriever


YUQUE_CATEGORY_PIPELINES = {"tutorial": ("tutorial", 1), "knowledge": ("knowledge", 1), "tool_card": ("tool_card", 1)}
WECHAT_CATEGORY_PIPELINES = {"product_review": ("product_review", 1), "purchase_guide": ("purchase_guide", 1)}


def embedding_provider():
    return OpenAICompatibleEmbedding(**settings.EMBEDDING)


def document_store():
    return DjangoDocumentStore()


def context_reader():
    return DjangoContextReader()


def _setting(value, name):
    # 评测可临时覆盖检索参数；不传时使用 settings。
    return getattr(settings, name) if value is None else value


# 关键词路搜索模式的使用范围 -> (文档分词器, 查询分词器)
KEYWORD_TOKENIZERS = {
    "off": (tokenize, tokenize),
    "document": (tokenize_for_search, tokenize),
    "both": (tokenize_for_search, tokenize_for_search),
}


def recall_collector(embedder, *, search_mode=None, synonyms=None):
    document_tokenizer, query_tokenizer = KEYWORD_TOKENIZERS[_setting(search_mode, "RETRIEVAL_KEYWORD_SEARCH_MODE")]
    synonyms = _setting(synonyms, "RETRIEVAL_KEYWORD_SYNONYMS")
    return MultiRouteRecall([
        KeywordRetriever(document_tokenizer, min_bm25=settings.RETRIEVAL_MIN_BM25,
                         query_tokenizer=query_tokenizer,
                         query_expander=default_expander() if synonyms else None),
        VectorRetriever(embedder, min_cosine=settings.RETRIEVAL_MIN_COSINE),
    ])


def post_recall_pipeline(*, rrf_k=None, rrf_weights=None):
    # 插入、移除或调序兼容步骤只修改这里；默认不启用模型重排。
    return PostRecallPipeline([
        RRFFusionStep(_setting(rrf_k, "RETRIEVAL_RRF_K"), _setting(rrf_weights, "RETRIEVAL_RRF_WEIGHTS")),
        GroupParentsStep(),
        TopKParentsStep(),
    ])


def preprocessors(*, counter=None, max_input_units=None):
    # Schema 是受信任应用代码的显式映射，不接受请求提供 Python 路径。
    parsers = ParserRegistry()
    parsers.register("text/x-yuque-markdown", YuqueMarkdownParser())

    def pipeline(schema, strategy, enrich=(), *, image_warning=None):
        chunker = BudgetChunker(
            max_input_units=settings.PREPROCESS_MAX_INPUT_BYTES if max_input_units is None else max_input_units,
            counter=counter,
        )
        parse = ParseStep(parsers) if image_warning is None else ParseStep(parsers, image_warning=image_warning)
        return PreprocessPipeline([
            parse, StructureStep(strategy), *enrich, ChunkStep(chunker),
            BuildDocumentStep(document_schema=schema),
            ValidateStep(input_validator=chunker.validate),
        ])

    registry = PreprocessorRegistry()
    registry.register("product_review", 1, pipeline("product_review", ReviewStrategy()))
    registry.register("purchase_guide", 1, pipeline("purchase_guide", PurchaseGuideStrategy()))
    registry.register("experience_case", 1, pipeline("experience_case", ExperienceCaseStrategy()))
    screenshot_warning = "原文含未转写的截图，操作界面以原文链接为准"
    for schema, profile in [("tutorial", TUTORIAL), ("knowledge", KNOWLEDGE)]:
        registry.register(schema, 1, pipeline(schema, SectionedDocumentStrategy(profile),
                                              [CalloutWarningStep(), TimeExpressionStep(), RetrievalPrefixStep()],
                                              image_warning=screenshot_warning))
    registry.register("tool_card", 1, pipeline("tool_card", ToolCardStrategy(), [
        ToolIdentityStep(), CalloutWarningStep(), SourceDateNoticeStep(), RetrievalPrefixStep(),
    ], image_warning=screenshot_warning))
    return registry
