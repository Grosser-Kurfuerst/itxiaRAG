import os
from pathlib import Path

from config.environment import boolean, bounded_float, positive_integer, required

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = required("DJANGO_SECRET_KEY")
DEBUG = boolean("DEBUG")
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
INSTALLED_APPS = [
    "django.contrib.auth", "django.contrib.contenttypes",
    "rest_framework", "rest_framework.authtoken", "catalog",
]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("POSTGRES_DB", "itxia"),
    "USER": os.environ.get("POSTGRES_USER", "itxia"),
    "PASSWORD": required("POSTGRES_PASSWORD"),
    "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
    "PORT": os.environ.get("POSTGRES_PORT", "5432"),
}}
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "UTC"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
REST_FRAMEWORK = {
    "DEFAULT_PARSER_CLASSES": ["api.parsers.LimitedJSONParser"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "api.errors.exception_handler",
}
EMBEDDING = {
    "base_url": os.environ.get("EMBEDDING_BASE_URL", ""),
    "model": os.environ.get("EMBEDDING_MODEL", ""),
    "dimensions": int(os.environ.get("EMBEDDING_DIMENSIONS", "0")),
    "revision": os.environ.get("EMBEDDING_REVISION", ""),
    "api_key": os.environ.get("EMBEDDING_API_KEY", ""),
    "query_prefix": os.environ.get("EMBEDDING_QUERY_PREFIX", ""),
}
RETRIEVAL_CANDIDATE_LIMIT = 100
RETRIEVAL_RRF_K = 60
RETRIEVAL_MIN_COSINE = bounded_float("RETRIEVAL_MIN_COSINE", None, -1, 1)
RETRIEVAL_MIN_BM25 = bounded_float("RETRIEVAL_MIN_BM25", 0.0, 0)
PREPROCESS_MAX_INPUT_BYTES = positive_integer("PREPROCESS_MAX_INPUT_BYTES", 2400)
