"""网页读取与快照的故障边界以替身验证，不开 socket；协议验证在集成测试中执行。"""
import json
from datetime import datetime, timezone
from http.client import HTTPMessage, IncompleteRead
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import quote

import pytest

from contracts.errors import DomainError
from sources.yuque.client import YuqueAccessDeniedError, YuqueDocRef, YuqueSnapshotClient, YuqueWebClient


pytestmark = pytest.mark.unit


def book_page(book_id, toc):
    data = quote(json.dumps({"book": {"id": book_id, "toc": toc}}))
    return f'<script>window.appData = JSON.parse(decodeURIComponent("{data}"));</script>'


def response(body, content_type):
    stream = BytesIO(body)
    stream.headers = HTTPMessage()
    stream.headers["Content-Type"] = f"{content_type}; charset=utf-8"
    return stream


@pytest.fixture
def ref():
    return YuqueDocRef(1, "help", "install", "合成安装", (), datetime(2025, 11, 23, tzinfo=timezone.utc))


@pytest.fixture
def client():
    return YuqueWebClient("synthetic", base_url="http://test", interval=0)


@pytest.mark.parametrize("body,content_type", [
    ("<html>合成验证码页</html>".encode(), "text/html"),
    (b"\xff", "text/markdown"),
])
def test_invalid_markdown_response_is_a_safe_domain_error(client, ref, body, content_type):
    with patch("sources.yuque.client.urlopen", return_value=response(body, content_type)):
        with pytest.raises(DomainError) as error:
            client.read_markdown(ref)
    assert error.value.code == "INVALID_YUQUE_RESPONSE"


@pytest.mark.parametrize("page", [
    "<html>没有 appData</html>",
    book_page(1, []).replace("%22book%22", "%22other%22"),
    book_page("1", []),
    book_page(1, None),
])
def test_invalid_book_page_is_a_listing_error(client, page):
    with patch("sources.yuque.client.urlopen", return_value=response(page.encode(), "text/html")):
        with pytest.raises(DomainError) as error:
            client.list_docs("help")
    assert error.value.code == "INVALID_YUQUE_RESPONSE"


@pytest.mark.parametrize("failure,code", [
    (URLError("synthetic-detail"), "YUQUE_UNAVAILABLE"),
    (TimeoutError("synthetic-detail"), "YUQUE_UNAVAILABLE"),
    (OSError("synthetic-detail"), "YUQUE_UNAVAILABLE"),
    (IncompleteRead(b"synthetic-detail"), "YUQUE_UNAVAILABLE"),
    (HTTPError("http://test", 429, "synthetic-detail", {}, None), "YUQUE_RATE_LIMITED"),
    (HTTPError("http://test", 503, "synthetic-detail", {}, None), "YUQUE_UNAVAILABLE"),
])
def test_transport_failures_do_not_expose_exception_details(client, ref, failure, code):
    with patch("sources.yuque.client.urlopen", side_effect=failure):
        with pytest.raises(DomainError) as error:
            client.read_markdown(ref)
    assert error.value.code == code
    assert "synthetic-detail" not in str(error.value)


@pytest.mark.parametrize("status", [401, 403])
def test_access_denied_is_not_a_per_document_domain_error(client, ref, status):
    failure = HTTPError("http://test", status, "synthetic-detail", {}, None)
    with patch("sources.yuque.client.urlopen", side_effect=failure):
        with pytest.raises(YuqueAccessDeniedError) as error:
            client.read_markdown(ref)
    assert not isinstance(error.value, DomainError)
    assert "synthetic-detail" not in str(error.value)


def test_default_interval_is_applied_after_previous_request_and_timeout_is_forwarded(ref):
    client = YuqueWebClient("synthetic", base_url="http://test", timeout=7)
    responses = [response("正文".encode(), "text/markdown") for _ in range(2)]
    with patch("sources.yuque.client.urlopen", side_effect=responses) as request, \
            patch("sources.yuque.client.time.monotonic", side_effect=[10, 10.6, 11.2]), \
            patch("sources.yuque.client.time.sleep") as sleep:
        assert client.read_markdown(ref) == client.read_markdown(ref) == "正文"
    sleep.assert_called_once()
    assert sleep.call_args.args[0] == pytest.approx(0.4)
    assert all(call.kwargs["timeout"] == 7 for call in request.call_args_list)


def test_snapshot_read_failure_removes_stale_body_and_keeps_successful_bodies(tmp_path, client, ref):
    metadata = {"id": 1, "slug": "install", "title": ref.title,
                "content_updated_at": ref.content_updated_at.isoformat()}
    with patch.object(client, "_get", side_effect=[book_page(1, []), json.dumps({"data": [metadata]})]):
        assert client.list_docs("help") == [ref]
    target = tmp_path / "help"
    target.mkdir()
    (target / "install.md").write_text("旧正文", encoding="utf-8")
    failure = DomainError("YUQUE_RATE_LIMITED", "合成限流")
    with patch.object(client, "read_markdown", side_effect=failure):
        assert client.save_snapshot(tmp_path, [ref]) == {"help/install": failure}
    assert not (target / "install.md").exists()
    assert YuqueSnapshotClient(tmp_path).list_docs("help") == [ref]
    with patch.object(client, "read_markdown", return_value="本轮合成正文"):
        assert client.save_snapshot(tmp_path, [ref]) == {}
    assert YuqueSnapshotClient(tmp_path).read_markdown(ref) == "本轮合成正文"
    assert json.loads((target / "docs.json").read_text()) == {"data": [metadata]}


def test_snapshot_write_failure_terminates_without_exposing_path(tmp_path, client):
    with patch.object(client, "_get", side_effect=[book_page(1, []), json.dumps({"data": []})]):
        client.list_docs("help")
    directory = tmp_path / "file"
    directory.write_text("blocking file")
    with pytest.raises(DomainError) as error:
        client.save_snapshot(directory, [])
    assert error.value.code == "SNAPSHOT_WRITE_FAILED"
    assert str(directory) not in str(error.value)
