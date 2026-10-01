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


def test_http_service_is_live_and_query_is_not_yet_ready():
    code, body = get("/health/live/")
    assert code == 200 and json.loads(body) == {"status": "live"}
    code, body = get("/health/ready/")
    assert code == 503 and json.loads(body) == {"status": "not_ready"}
    assert get("/api/schema/")[0] == 401
    for path in ("/api/v1/sources/", "/api/v1/search/"):
        assert get(path)[0] == 404
