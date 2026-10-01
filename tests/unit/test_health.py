from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.test import RequestFactory

from config.health import health_live, health_ready

pytestmark = pytest.mark.unit


def test_live_health_does_not_access_database():
    response = health_live(RequestFactory().get("/health/live/"))
    assert response.status_code == 200
    assert response.content == b'{"status": "live"}'


def test_database_failure_is_safe_and_not_ready(caplog):
    with patch("config.health.connection.cursor", side_effect=OperationalError("secret-password")):
        response = health_ready(RequestFactory().get("/health/ready/"))
    assert response.status_code == 503
    assert b"secret-password" not in response.content
    assert "secret-password" not in caplog.text
    assert any(getattr(r, "event", None) == "database_unavailable" for r in caplog.records)


def test_healthy_database_does_not_claim_query_readiness():
    with patch("config.health.connection.cursor"):
        response = health_ready(RequestFactory().get("/health/ready/"))
    assert response.status_code == 503
