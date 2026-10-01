import pytest
from django.urls import Resolver404, resolve

pytestmark = pytest.mark.contract


def test_health_routes_exist_without_business_route_stubs():
    assert resolve("/health/live/").url_name == "health-live"
    assert resolve("/health/ready/").url_name == "health-ready"
    assert resolve("/api/v1/search/").url_name == "search"
    with pytest.raises(Resolver404):
        resolve("/api/v1/feedback/")
