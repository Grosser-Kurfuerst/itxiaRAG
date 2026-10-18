"""MCP 服务：向 persona 提供知识检索与机型推荐两个工具。"""
import json

import anyio
from django.conf import settings
from django.db import close_old_connections
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from rest_framework.utils.encoders import JSONEncoder

from api.operations import run_recommend, run_search
from contracts.errors import DomainError
from contracts.products import ConditionsArg, Preference, RecommendInput, RecommendTopK
from contracts.query import FiltersArg, QueryInput, QueryText, SearchTopK

SEARCH_DESCRIPTION = (
    "检索 IT 侠知识库（评测、购机指南、教程、知识、工具、排障经验，含校园网、软件与维修），返回完整段落及来源。"
    "用于具体机型的事实、配置以及使用、软件、网络、维修问题，不用于按条件挑机型。"
)
RECOMMEND_DESCRIPTION = (
    "按原子条件从已评测的笔记本中筛选机型，并按 preference 在评测正文中排序。返回规格卡、评测结论和与偏好相关的评测段落。"
    "口语条件需先按提示词中的参考口径换算。字段没有数据的机型视为不满足该条件。结果为空时返回 diagnostics，系统不会自动放宽条件。"
)

mcp = MCPServer("itxia-kb")


def in_worker(operation, args, user):
    close_old_connections()
    try:
        return operation(args, user)
    finally:
        close_old_connections()


def current_user(ctx):
    return ctx.request_context.request.scope["user"]  # 由 TokenAuthMiddleware 写入


async def call_tool(operation, args, ctx):
    try:
        result = await anyio.to_thread.run_sync(in_worker, operation, args, current_user(ctx))
    except DomainError as error:
        raise ToolError(json.dumps({"error": {"code": error.code, "message": error.message}},
                                   ensure_ascii=False)) from None
    return json.dumps(result, cls=JSONEncoder, ensure_ascii=False)


@mcp.tool(description=SEARCH_DESCRIPTION, structured_output=False)
async def search_knowledge(query: QueryText, filters: FiltersArg, top_k: SearchTopK = 5,
                           ctx: Context = None) -> str:
    return await call_tool(run_search, QueryInput(query=query, filters=filters, top_k=top_k), ctx)


@mcp.tool(description=RECOMMEND_DESCRIPTION, structured_output=False)
async def recommend_laptops(conditions: ConditionsArg, preference: Preference = "",
                            top_k: RecommendTopK = 5, ctx: Context = None) -> str:
    return await call_tool(run_recommend, RecommendInput(conditions=conditions, preference=preference, top_k=top_k), ctx)


def http_app():
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[*settings.ALLOWED_HOSTS, *(f"{host}:*" for host in settings.ALLOWED_HOSTS)],
        ),
    )
