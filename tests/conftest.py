import json
from pathlib import Path

import pytest


@pytest.fixture
def document_payload():
    return json.loads((Path(__file__).resolve().parents[1] / "fixtures/iteration1/basic.json").read_text())


class TestEmbedding:
    """只用于断言检索行为；不代表真实模型效果。"""
    space_id = "test-space-v1"

    def embed_documents(self, texts):
        return [[1.0, 0.0] if "续航" in text else [0.0, 1.0] for text in texts]

    def embed_query(self, text):
        return [1.0, 0.0] if "电池" in text or "续航" in text else [0.0, 1.0]


@pytest.fixture
def embedder():
    return TestEmbedding()
