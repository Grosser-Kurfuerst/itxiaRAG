from django.urls import path

from api.views import JobRetryView, JobView, SourceImportView, SourceUpdateImportView
from api.views import JobReviewView, JobPublishView, SourceView, SourceWithdrawView, ContextView, EvidenceView
from api.views import SearchView

urlpatterns = [
    path("search/", SearchView.as_view(), name="search"),
    path("sources/", SourceImportView.as_view(), name="source-import"),
    path("sources/<uuid:id>/imports/", SourceUpdateImportView.as_view(), name="source-update-import"),
    path("import-jobs/<uuid:id>/", JobView.as_view(), name="job"),
    path("import-jobs/<uuid:id>/retry/", JobRetryView.as_view(), name="job-retry"),
    path("import-jobs/<uuid:id>/review/", JobReviewView.as_view(), name="job-review"),
    path("import-jobs/<uuid:id>/publish/", JobPublishView.as_view(), name="job-publish"),
    path("sources/<uuid:id>/", SourceView.as_view(), name="source"),
    path("sources/<uuid:id>/withdraw/", SourceWithdrawView.as_view(), name="source-withdraw"),
    path("contexts/<uuid:id>/", ContextView.as_view(), name="context"),
    path("evidence/<uuid:id>/", EvidenceView.as_view(), name="evidence"),
]
