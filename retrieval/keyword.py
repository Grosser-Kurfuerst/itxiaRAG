import re

from django.db.models import Case, IntegerField, Q, Value, When

from catalog.selectors import scoped_evidence
from contracts.types import Candidate, SearchScope


def terms(query, max_terms=16):
    pieces = re.split(r"[\s,，。?？;；!！、:：()（）\[\]【】\"“”‘’]+", query.strip())
    values, seen = [], set()
    for item in pieces:
        if item and any(char.isalnum() for char in item) and item.casefold() not in seen:
            seen.add(item.casefold())
            values.append(item)
    return [query.strip()] if len(values) > max_terms else values



class KeywordRetriever:
    name = "keyword"

    def search(self, query, scope, limit=100):
        words = terms(query)
        if not words:
            return []
        phrase = Q(retrieval_text__icontains=query)
        match, score = phrase, Case(When(phrase, then=Value(100)), default=Value(0), output_field=IntegerField())
        for word in words:
            condition = Q(retrieval_text__icontains=word)
            match |= condition
            score += Case(When(condition, then=Value(10)), default=Value(0), output_field=IntegerField())
            score += Case(When(context__title__icontains=word, then=Value(20)), default=Value(0), output_field=IntegerField())
        rows = (scoped_evidence(scope).filter(match).annotate(match_score=score)
                .order_by("-match_score", "id").values_list("id", "context_id", "match_score")[:limit])
        return [Candidate(evidence_id, context_id, float(value), {self.name: rank})
                for rank, (evidence_id, context_id, value) in enumerate(rows, 1)]
