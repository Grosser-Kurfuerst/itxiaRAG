from catalog.policies import visible_scopes
from contracts.types import ContextReader, Retriever, SearchScope


def search(data, actor, *, retriever: Retriever, reader: ContextReader,
           embedding_space: str, candidate_limit=100):
    filters = data.get("filters", {})
    scope = SearchScope(
        tuple(visible_scopes(actor)), embedding_space,
        tuple(filters["source_ids"]) if "source_ids" in filters else None,
        tuple(filters["knowledge_types"]) if "knowledge_types" in filters else None,
    )
    candidates = retriever.search(data["query"], scope, candidate_limit)
    contexts = reader.read(candidates, scope, data.get("top_k", 5))
    return {"mode": "hybrid", "result_status": "found" if contexts else "no_result",
            "contexts": contexts}
