import json
import os
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.e2e


def get(path):
    url = os.environ.get("KB_TEST_BASE_URL", "http://127.0.0.1:8000") + path
    try:
        response = urlopen(url, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.read()


def test_http_service_and_query_are_ready():
    code, body = get("/health/live/")
    assert code == 200 and json.loads(body) == {"status": "live"}
    code, body = get("/health/ready/")
    assert code == 200 and json.loads(body) == {"status": "ready"}
    assert get("/api/schema/")[0] == 401
    assert get("/api/v1/sources/")[0] == 401
    assert get("/api/v1/search/")[0] == 401
    assert get("/api/v1/feedback/")[0] == 404
