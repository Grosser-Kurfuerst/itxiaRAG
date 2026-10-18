"""检索与推荐的装配代码；REST 和 MCP 共用。"""
from django.conf import settings

from catalog.policies import visible_scopes
from config import components
from contracts.products import RecommendInput
from contracts.query import QueryInput
from products.service import recommend
from retrieval.service import search


def run_search(args: QueryInput, user):
    embedder = components.embedding_provider()
    return search(args.model_dump(exclude_none=True), visible_scopes(user),
                  collector=components.recall_collector(embedder), pipeline=components.post_recall_pipeline(),
                  reader=components.context_reader(), embedding_space=embedder.space_id,
                  candidate_limit=settings.RETRIEVAL_CANDIDATE_LIMIT)


def run_recommend(args: RecommendInput, user):
    embedder = components.embedding_provider()
    return recommend(args.model_dump(exclude_none=True), visible_scopes(user),
                     collector=components.recall_collector(embedder), pipeline=components.post_recall_pipeline(),
                     embedding_space=embedder.space_id, candidate_limit=settings.RETRIEVAL_CANDIDATE_LIMIT)
