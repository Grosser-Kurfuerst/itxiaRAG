"""兼容 /embeddings 的 HTTP 适配器；也可连接本地模型服务。"""
import hashlib
import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from contracts.errors import DomainError
from embeddings.validation import validate_vectors


class OpenAICompatibleEmbedding:
    def __init__(self, *, base_url, model, dimensions, revision, api_key="",
                 query_prefix="", timeout=30, batch_size=32):
        if not base_url or not model or not revision or dimensions < 1:
            raise DomainError("EMBEDDING_NOT_CONFIGURED", "请配置 Embedding 地址、模型、维度和版本", 503)
        self.url = base_url.rstrip("/") + "/embeddings"
        self.model, self.dimensions, self.api_key = model, dimensions, api_key
        self.query_prefix, self.timeout, self.batch_size = query_prefix, timeout, batch_size
        # 模型、服务、预处理与版本共同标识向量空间，避免混用同维不同模型。
        identity = [base_url.rstrip("/"), model, dimensions, revision, query_prefix, "title-body-v1"]
        self.space_id = hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def _embed(self, texts):
        request = Request(self.url, method="POST", data=json.dumps({
            "model": self.model, "input": texts,
        }).encode("utf-8"), headers={"Content-Type": "application/json"})
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except (URLError, TimeoutError, OSError):
            raise DomainError("EMBEDDING_UNAVAILABLE", "Embedding 服务调用失败", 502) from None
        except (ValueError, UnicodeError):
            raise DomainError("INVALID_EMBEDDING", "Embedding 服务返回格式错误", 502) from None
        try:
            rows = sorted(payload["data"], key=lambda item: item["index"])
            if [row["index"] for row in rows] != list(range(len(texts))):
                raise ValueError
            vectors = [row["embedding"] for row in rows]
        except (KeyError, TypeError, ValueError):
            raise DomainError("INVALID_EMBEDDING", "Embedding 服务返回格式错误", 502) from None
        return validate_vectors(vectors, len(texts), self.dimensions)

    def embed_documents(self, texts):
        vectors = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed(texts[start:start + self.batch_size]))
        return vectors

    def embed_query(self, text):
        return self._embed([self.query_prefix + text])[0]
