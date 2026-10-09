"""只替换 HTTP 边界，不开 socket；协议验证在集成测试中执行。"""
import json
from datetime import datetime, timezone
from http.client import IncompleteRead
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from contracts.errors import DomainError
from sources.yuque.client import YuqueAuthenticationError, YuqueDocRef, YuqueOpenApiClient


pytestmark = pytest.mark.unit
REF = YuqueDocRef(1, "help", "install", "合成教程", (), datetime(2025, 1, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize("body", [b"{", b"\xff", b"[]", b'{"data": {}}', b'{"data": {"body": 1}}'])
def test_invalid_response_is_a_safe_domain_error(body):
    client = YuqueOpenApiClient("http://test/api/v2", "synthetic-secret", "synthetic", interval=0)
    with patch("sources.yuque.client.urlopen", return_value=BytesIO(body)):
        with pytest.raises(DomainError) as error:
            client.read_markdown(REF)
    assert error.value.code == "INVALID_YUQUE_RESPONSE"


@pytest.mark.parametrize("failure,code", [
    (URLError("synthetic-secret"), "YUQUE_UNAVAILABLE"),
    (TimeoutError("synthetic-secret"), "YUQUE_UNAVAILABLE"),
    (OSError("synthetic-secret"), "YUQUE_UNAVAILABLE"),
    (IncompleteRead(b"synthetic-secret"), "YUQUE_UNAVAILABLE"),
    (HTTPError("http://test", 429, "synthetic-secret", {}, None), "YUQUE_RATE_LIMITED"),
    (HTTPError("http://test", 503, "synthetic-secret", {}, None), "YUQUE_UNAVAILABLE"),
])
def test_transport_failures_do_not_expose_exception_details(failure, code):
    client = YuqueOpenApiClient("http://test/api/v2", "synthetic-secret", "synthetic", interval=0)
    with patch("sources.yuque.client.urlopen", side_effect=failure):
        with pytest.raises(DomainError) as error:
            client.read_markdown(REF)
    assert error.value.code == code
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_error_is_not_a_per_document_domain_error(status):
    client = YuqueOpenApiClient("http://test/api/v2", "synthetic-secret", "synthetic", interval=0)
    failure = HTTPError("http://test", status, "synthetic-secret", {}, None)
    with patch("sources.yuque.client.urlopen", side_effect=failure):
        with pytest.raises(YuqueAuthenticationError) as error:
            client.read_markdown(REF)
    assert not isinstance(error.value, DomainError)
    assert "synthetic-secret" not in str(error.value)


def test_default_interval_is_applied_after_previous_request_and_timeout_is_forwarded():
    client = YuqueOpenApiClient("http://test/api/v2", "synthetic-secret", "synthetic", timeout=7)
    responses = [BytesIO(json.dumps({"data": {"body": "正文"}}).encode()) for _ in range(2)]
    with patch("sources.yuque.client.urlopen", side_effect=responses) as request, \
            patch("sources.yuque.client.time.monotonic", side_effect=[10, 10.1, 10.6]), \
            patch("sources.yuque.client.time.sleep") as sleep:
        assert client.read_markdown(REF) == client.read_markdown(REF) == "正文"
    sleep.assert_called_once()
    assert sleep.call_args.args[0] == pytest.approx(0.4)
    assert all(call.kwargs["timeout"] == 7 for call in request.call_args_list)
