import json
from unittest.mock import patch

import anyio
import httpx2
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from mcp_types import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_VERSION_META_KEY
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from rest_framework.utils.encoders import JSONEncoder

from catalog.storage import DjangoDocumentStore
from contracts.products import PORTS
from contracts.serializers import SourceImportSerializer, import_dtos
from ingestion.pipeline import import_processed
from mcp_server.auth import TokenAuthMiddleware
from mcp_server.server import http_app, mcp
from products.importing import import_specs

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

BASE_URL = "http://127.0.0.1:8001"


def import_review(embedder, title, source_date, chunks, visibility="public"):
    payload = {
        "source": {"source_type": "manual", "canonical_locator": f"example:{title}", "visibility": visibility},
        "document": {"title": f"{title} 评测", "document_schema": "product_review", "source_date": source_date,
                     "contexts": [{"key": "review", "title": title, "body": "\n".join(body for body, _ in chunks),
                                   "children": [{"key": f"chunk-{number}", "body": body, "metadata": {"sections": sections}}
                                                for number, (body, sections) in enumerate(chunks, 1)]}]},
    }
    serializer = SourceImportSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    import_processed(*import_dtos(serializer.validated_data), embedder=embedder, store=DjangoDocumentStore())


def spec(key, **fields):
    return {"key": key, "brand": key.split()[0], "ports": dict.fromkeys(PORTS, False), **fields}


@pytest.fixture
def catalog(embedder):
    import_review(embedder, "联想 游戏本", "2026-09-01", [
        ("配置为 RTX 5070。", ["配置"]), ("日常续航约 9 小时。", ["续航"]), ("购买建议：值得买。", ["购买建议"])])
    import_review(embedder, "雷蛇 内部样机", "2026-10-01", [("内部续航资料。", ["总结"])], visibility="internal")
    report = import_specs([
        spec("联想 游戏本", price_cny=9999, has_dgpu=True, gpu="RTX 5070", is_gaming=True),
        spec("雷蛇 内部样机", price_cny=8999, has_dgpu=False),
    ])
    assert not report.failed


def user_token(permissions=()):
    user = get_user_model().objects.create_user(f"mcp-{'-'.join(permissions) or 'reader'}")
    user.user_permissions.set(Permission.objects.filter(codename__in=permissions))
    return Token.objects.create(user=user).key


def plain(data):
    return json.loads(json.dumps(data, cls=JSONEncoder))


def rest_call(token, path, payload, embedder):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    with patch("config.components.embedding_provider", return_value=embedder):
        response = client.post(path, payload, format="json")
    assert response.status_code == 200, response.data
    return plain(response.data)


def run_mcp(calls, token=None, base_url=BASE_URL, embedder=None):
    async def main():
        app = TokenAuthMiddleware(http_app())
        async with mcp.session_manager.run():
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=base_url) as client:
                return await calls(client, token)

    with patch("config.components.embedding_provider", return_value=embedder):
        return anyio.run(main)


def legacy_headers(token=None):
    return {"Accept": "application/json", **({"Authorization": f"Token {token}"} if token else {})}


async def legacy(client, token, method, params, request_id):
    response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": request_id, "method": method,
                                               "params": params}, headers=legacy_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def initialize(client, token):
    return await legacy(client, token, "initialize", {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "itxia-test", "version": "1"},
    }, 1)


def modern_headers(token, method, name=None):
    headers = {**legacy_headers(token), "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method}
    if name:
        headers["Mcp-Name"] = name
    return headers


def modern_params(params):
    return {**params, "_meta": {PROTOCOL_VERSION_META_KEY: "2026-07-28", CLIENT_CAPABILITIES_META_KEY: {}}}


def test_legacy_handshake_tools_and_results_match_rest(catalog, embedder):
    token = user_token()

    async def calls(client, token):
        initialized = await initialize(client, token)
        assert initialized["protocolVersion"] == "2025-11-25"
        listed = await legacy(client, token, "tools/list", {}, 2)
        search = await legacy(client, token, "tools/call", {
            "name": "search_knowledge", "arguments": {"query": "续航"}}, 3)
        recommend = await legacy(client, token, "tools/call", {
            "name": "recommend_laptops", "arguments": {"conditions": {"price_max": 10000}}}, 4)
        return listed, search, recommend

    listed, search, recommend = run_mcp(calls, token, embedder=embedder)
    assert sorted(tool["name"] for tool in listed["tools"]) == ["recommend_laptops", "search_knowledge"]
    assert all("inputSchema" in tool for tool in listed["tools"])
    assert not search["isError"] and json.loads(search["content"][0]["text"]) == rest_call(
        token, "/api/v1/search/", {"query": "续航"}, embedder)
    assert not recommend["isError"] and json.loads(recommend["content"][0]["text"]) == rest_call(
        token, "/api/v1/products/recommend/", {"conditions": {"price_max": 10000}}, embedder)


def test_modern_protocol_lists_tools_without_handshake(catalog):
    token = user_token()

    async def calls(client, token):
        response = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": modern_params({}),
        }, headers=modern_headers(token, "tools/list"))
        assert response.status_code == 200, response.text
        return response.json()["result"]

    result = run_mcp(calls, token)
    assert sorted(tool["name"] for tool in result["tools"]) == ["recommend_laptops", "search_knowledge"]


def test_visibility_is_applied_to_mcp_search(catalog, embedder):
    reader, internal = user_token(), user_token(["read_internal"])

    async def calls(client, token):
        await initialize(client, token)
        result = await legacy(client, token, "tools/call", {
            "name": "search_knowledge", "arguments": {"query": "续航"}}, 2)
        return json.loads(result["content"][0]["text"])

    public = run_mcp(calls, reader, embedder=embedder)
    with_internal = run_mcp(calls, internal, embedder=embedder)
    assert {row["source"]["title"] for row in public["contexts"]} == {"联想 游戏本 评测"}
    assert {row["source"]["title"] for row in with_internal["contexts"]} == {"联想 游戏本 评测", "雷蛇 内部样机 评测"}


def test_missing_token_and_bad_host_are_rejected():
    async def no_token(client, _):
        response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                                     headers=legacy_headers())
        return response

    response = run_mcp(no_token)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"

    token = user_token()

    async def bad_host(client, token):
        return await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                                 headers=legacy_headers(token))

    response = run_mcp(bad_host, token, base_url="http://badhost:8001")
    assert response.status_code == 421
