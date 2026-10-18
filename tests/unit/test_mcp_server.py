import asyncio
import json
from datetime import date
from unittest.mock import patch
from uuid import UUID

import pytest
from mcp import Client
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.utils.encoders import JSONEncoder

from contracts.errors import DomainError
from contracts.products import RecommendInput
from contracts.query import QueryInput
from mcp_server import server
from mcp_server.auth import TokenAuthMiddleware


def tools():
    return {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}


def test_tools_names_descriptions_and_top_level_arguments_match_contracts():
    listed = tools()
    assert sorted(listed) == ["recommend_laptops", "search_knowledge"]
    assert listed["search_knowledge"].description == server.SEARCH_DESCRIPTION
    assert listed["recommend_laptops"].description == server.RECOMMEND_DESCRIPTION

    for name, model in [("search_knowledge", QueryInput), ("recommend_laptops", RecommendInput)]:
        schema = listed[name].input_schema
        expected = model.model_json_schema()
        assert schema["properties"] == expected["properties"]
        assert schema.get("required", []) == expected.get("required", [])
        assert schema["$defs"] == expected["$defs"]


def test_generated_schema_has_no_null_type_branch():
    def null_types(value):
        if isinstance(value, dict):
            value_type = value.get("type")
            assert not (isinstance(value_type, list) and "null" in value_type)
            assert value_type != "null"
            for item in value.values():
                null_types(item)
        elif isinstance(value, list):
            for item in value:
                null_types(item)

    for tool in tools().values():
        null_types(tool.input_schema)


def call_tool(name, arguments):
    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(call())


def test_success_is_json_text_without_structured_content():
    result_value = {"id": UUID("00000000-0000-0000-0000-000000000001"), "date": date(2026, 10, 18)}
    with patch.object(server, "current_user", return_value=object()), \
            patch.object(server, "run_search", return_value=result_value):
        result = call_tool("search_knowledge", {"query": "续航", "filters": None})
    assert not result.is_error and result.structured_content is None
    assert result.content[0].text == json.dumps(result_value, cls=JSONEncoder, ensure_ascii=False)

    with patch.object(server, "current_user", return_value=object()), \
            patch.object(server, "run_recommend", return_value={"products": []}):
        result = call_tool("recommend_laptops", {"conditions": None})
    assert not result.is_error and json.loads(result.content[0].text) == {"products": []}


def test_parameter_validation_error_is_returned_by_sdk():
    with patch.object(server, "current_user", return_value=object()):
        result = call_tool("search_knowledge", {"query": "续航", "top_k": 50})
    assert result.is_error and "less than or equal to 20" in result.content[0].text


def test_domain_error_body_matches_rest():
    error = DomainError("EMBEDDING_UNAVAILABLE", "模型不可用", 502)
    with patch.object(server, "current_user", return_value=object()), \
            patch.object(server, "run_search", side_effect=error):
        result = call_tool("search_knowledge", {"query": "续航"})
    assert result.is_error
    body = result.content[0].text.removeprefix("Error executing tool search_knowledge: ")
    assert json.loads(body) == {
        "error": {"code": "EMBEDDING_UNAVAILABLE", "message": "模型不可用"}}


def test_unexpected_error_hides_details():
    with patch.object(server, "current_user", return_value=object()), \
            patch.object(server, "run_search", side_effect=RuntimeError("secret")):
        result = call_tool("search_knowledge", {"query": "续航"})
    assert result.is_error
    assert result.content[0].text == "Error executing tool search_knowledge"
    assert "secret" not in result.content[0].text


def asgi_call(headers=(), scope_type="http"):
    sent = []
    captured = {}

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        captured["scope"] = scope
        if scope["type"] == "lifespan":
            await send({"type": "lifespan.startup.complete"})
        else:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

    if scope_type == "lifespan":
        scope = {"type": "lifespan"}

        async def receive():
            return {"type": "lifespan.startup"}
    else:
        scope = {
            "type": scope_type,
            "method": "POST",
            "path": "/mcp",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers],
            "query_string": b"",
            "server": ("127.0.0.1", 8001),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "root_path": "",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
    asyncio.run(TokenAuthMiddleware(downstream)(scope, receive, send))
    return sent, captured


@pytest.mark.parametrize("scheme", ["Token", "Bearer", "token"])
def test_auth_accepts_token_and_bearer(scheme):
    user = object()
    with patch.object(TokenAuthentication, "authenticate_credentials", return_value=(user, None)):
        sent, captured = asgi_call([("Authorization", f"{scheme} abc")])
    assert sent[0]["status"] == 200 and captured["scope"]["user"] is user


@pytest.mark.parametrize("headers", [
    [],
    [("Authorization", "Basic abc")],
    [("Authorization", "Token ")],
])
def test_auth_rejects_missing_or_malformed_token(headers):
    sent, _ = asgi_call(headers)
    assert sent[0]["status"] == 401
    assert json.loads(sent[1]["body"])["error"]["code"] == "NOT_AUTHENTICATED"


def test_auth_rejects_invalid_token():
    with patch.object(TokenAuthentication, "authenticate_credentials", side_effect=AuthenticationFailed()):
        sent, _ = asgi_call([("Authorization", "Token bad")])
    assert sent[0]["status"] == 401
    assert json.loads(sent[1]["body"])["error"]["message"] == "认证失败"


def test_auth_passes_lifespan_without_token():
    sent, captured = asgi_call(scope_type="lifespan")
    assert sent == [{"type": "lifespan.startup.complete"}] and captured["scope"]["type"] == "lifespan"
