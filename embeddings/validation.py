import math

from contracts.errors import DomainError


def validate_vectors(vectors, count, dimensions=None):
    error = DomainError("INVALID_EMBEDDING", "向量数量、维度或数值不合法", 502)
    if not isinstance(vectors, list) or len(vectors) != count:
        raise error
    size = dimensions or (len(vectors[0]) if vectors and isinstance(vectors[0], list) else 0)
    for vector in vectors:
        if not isinstance(vector, list) or not vector or len(vector) != size:
            raise error
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
            raise error
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise error
    return vectors
