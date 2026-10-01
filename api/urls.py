from django.urls import path

from api.views import JobRetryView, JobView, SourceImportView, SourceUpdateImportView

urlpatterns = [
    path("sources/", SourceImportView.as_view(), name="source-import"),
    path("sources/<uuid:id>/imports/", SourceUpdateImportView.as_view(), name="source-update-import"),
    path("import-jobs/<uuid:id>/", JobView.as_view(), name="job"),
    path("import-jobs/<uuid:id>/retry/", JobRetryView.as_view(), name="job-retry"),
]
