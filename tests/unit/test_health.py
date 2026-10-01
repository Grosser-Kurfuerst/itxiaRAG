from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.test import RequestFactory

from config.health import health_live, health_ready
from contracts.errors import DomainError

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


def test_invalid_profiles_do_not_claim_readiness():
    with patch("config.health.connection.cursor"), patch("config.health.active_profiles", side_effect=DomainError("PROFILE_INVALID", "配置损坏", 503)):
        response = health_ready(RequestFactory().get("/health/ready/"))
    assert response.status_code == 503
