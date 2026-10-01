import os

# pytest-django 在测试导入前读取设置；仅为离线检查提供测试配置。
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-not-for-running-the-app")
os.environ.setdefault("POSTGRES_PASSWORD", "test-only-password")


def pytest_addoption(parser):
    parser.addoption("--step", default="S6", help="迭代一验收范围 S0～S6")
