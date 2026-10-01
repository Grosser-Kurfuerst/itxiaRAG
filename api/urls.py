from django.urls import path

from api.views import SearchView, SourceImportView

urlpatterns = [
    path("sources/", SourceImportView.as_view(), name="source-import"),
    path("search/", SearchView.as_view(), name="search"),
]
