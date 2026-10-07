from catalog.policies import visible_scopes
from contracts.types import ContextReader, RecallCollector, SearchPipeline, SearchRequest, SearchScope


def search(data, actor, *, collector: RecallCollector, pipeline: SearchPipeline, reader: ContextReader,
           embedding_space: str, candidate_limit=100):
    filters = data.get("filters", {})
    scope = SearchScope(
        tuple(visible_scopes(actor)), embedding_space,
        tuple(filters["source_ids"]) if "source_ids" in filters else None,
    )
    request = SearchRequest(data["query"], scope, data.get("top_k", 5))
    routes = collector.collect(request.query, scope, candidate_limit)
    parents = pipeline.run(request, routes)
    contexts = reader.read(parents.contexts, scope)
    return {"mode": "hybrid", "result_status": "found" if contexts else "no_result",
            "contexts": contexts}
