"""仅 pytest 使用；应用启动仍要求显式配置密钥。"""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret")
os.environ.setdefault("POSTGRES_PASSWORD", "test-only-password")

from config.settings import *  # noqa: F403
