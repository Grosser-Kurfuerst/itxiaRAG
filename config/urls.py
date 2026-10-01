from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.permissions import BasePermission

from .health import health_live, health_ready


class MaintainerPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.has_perm("catalog.maintain_source"))


class ProtectedSchemaView(SpectacularAPIView):
    permission_classes = [MaintainerPermission]


urlpatterns = [
    path("health/live/", health_live, name="health-live"),
    path("health/ready/", health_ready, name="health-ready"),
    path("api/schema/", ProtectedSchemaView.as_view(), name="schema"),
    path("api/v1/", include("api.urls")),
]
