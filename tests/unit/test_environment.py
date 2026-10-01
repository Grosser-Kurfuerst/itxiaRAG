import pytest
from django.core.exceptions import ImproperlyConfigured

from config.environment import boolean, required

pytestmark = pytest.mark.unit


def test_missing_secret_fails_without_echoing_value(monkeypatch):
    monkeypatch.delenv("MISSING_TEST_SECRET", raising=False)
    with pytest.raises(ImproperlyConfigured, match="MISSING_TEST_SECRET"):
        required("MISSING_TEST_SECRET")


def test_invalid_boolean_is_not_silently_enabled(monkeypatch):
    monkeypatch.setenv("DEBUG", "unexpected-private-value")
    with pytest.raises(ImproperlyConfigured) as caught:
        boolean("DEBUG")
    assert "unexpected-private-value" not in str(caught.value)
