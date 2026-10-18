"""uvicorn 入口：uvicorn mcp_server.asgi:app --host 0.0.0.0 --port 8001"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from mcp_server.auth import TokenAuthMiddleware  # noqa: E402
from mcp_server.server import http_app  # noqa: E402

app = TokenAuthMiddleware(http_app())
