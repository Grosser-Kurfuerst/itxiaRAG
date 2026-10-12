from django.urls import path

from api.views import ProductRecommendView, RawSourceImportView, SearchView, SourceImportView

urlpatterns = [
    path("sources/", SourceImportView.as_view(), name="source-import"),
    path("sources/raw/", RawSourceImportView.as_view(), name="raw-source-import"),
    path("search/", SearchView.as_view(), name="search"),
    path("products/recommend/", ProductRecommendView.as_view(), name="product-recommend"),
]
