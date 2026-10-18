"""MCP 的 Token 认证中间件；与 REST 共用 DRF Token 表。"""
import anyio
from django.db import close_old_connections
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
from starlette.datastructures import Headers
from starlette.responses import JSONResponse


def token_from_header(value):
    scheme, _, key = value.partition(" ")
    return key.strip() if scheme.casefold() in {"token", "bearer"} and key.strip() else None


def authenticate(key):
    close_old_connections()
    try:
        user, _ = TokenAuthentication().authenticate_credentials(key)
        return user
    finally:
        close_old_connections()


def unauthorized():
    return JSONResponse({"error": {"code": "NOT_AUTHENTICATED", "message": "认证失败"}}, status_code=401)


class TokenAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        key = token_from_header(Headers(scope=scope).get("authorization", ""))
        if key is None:
            return await unauthorized()(scope, receive, send)
        try:
            user = await anyio.to_thread.run_sync(authenticate, key)
        except AuthenticationFailed:
            return await unauthorized()(scope, receive, send)
        scope["user"] = user
        await self.app(scope, receive, send)
