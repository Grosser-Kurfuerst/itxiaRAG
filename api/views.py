from catalog import services, selectors, presenters
from contracts.serializers import (ReviewSerializer, SourcePatchSerializer, SourceResponseSerializer,
                                   ContextResponseSerializer, EvidenceResponseSerializer)

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.policies import require_permission
from catalog.presenters import job_report, job_summary
from catalog.selectors import maintenance_job
from contracts.serializers import (EmptyObject, ImportContentSerializer, JobReportSerializer,
                                   JobSummarySerializer, SourceImportSerializer)
from ingestion.pipeline import import_text, resume_import
from contracts.query import QuerySerializer, SearchResponseSerializer
from retrieval.service import search
from uuid import uuid4


def validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class SourceImportView(APIView):
    @extend_schema(request=SourceImportSerializer, responses={200: JobSummarySerializer})
    def post(self, request):
        require_permission(request.user, "maintain_source")
        data = validated(SourceImportSerializer, request.data)
        job, reused = import_text(data, request.user)
        return Response(JobSummarySerializer(job_summary(job, reused)).data)


class SourceUpdateImportView(APIView):
    @extend_schema(request=ImportContentSerializer, responses={200: JobSummarySerializer})
    def post(self, request, id):
        require_permission(request.user, "maintain_source")
        data = validated(ImportContentSerializer, request.data)
        job, reused = import_text(data, request.user, source_id=id)
        return Response(JobSummarySerializer(job_summary(job, reused)).data)


class JobView(APIView):
    @extend_schema(responses={200: JobReportSerializer})
    def get(self, request, id):
        job = maintenance_job(id, request.user)
        return Response(JobReportSerializer(job_report(job)).data)


class JobRetryView(APIView):
    @extend_schema(request=EmptyObject, responses={200: JobSummarySerializer})
    def post(self, request, id):
        require_permission(request.user, "maintain_source")
        validated(EmptyObject, request.data)
        job = resume_import(id, request.user, retry=True)
        return Response(JobSummarySerializer(job_summary(job)).data)


class JobReviewView(APIView):
    @extend_schema(request=ReviewSerializer, responses={200: JobSummarySerializer})
    def post(self, request, id):
        require_permission(request.user, "review_import")
        data = validated(ReviewSerializer, request.data)
        job = services.review_job(id, actor=request.user, **data)
        return Response(JobSummarySerializer(job_summary(job)).data)


class JobPublishView(APIView):
    @extend_schema(request=EmptyObject, responses={200: JobSummarySerializer})
    def post(self, request, id):
        require_permission(request.user, "maintain_source")
        validated(EmptyObject, request.data)
        job = services.publish_build(id, request.user)
        return Response(JobSummarySerializer(job_summary(job)).data)


class SourceView(APIView):
    @extend_schema(request=SourcePatchSerializer, responses={200: SourceResponseSerializer})
    def patch(self, request, id):
        require_permission(request.user, "maintain_source")
        data = validated(SourcePatchSerializer, request.data)
        source = services.update_source(id, data, request.user)
        return Response(SourceResponseSerializer(presenters.source_summary(source)).data)


class SourceWithdrawView(APIView):
    @extend_schema(request=EmptyObject, responses={200: SourceResponseSerializer})
    def post(self, request, id):
        require_permission(request.user, "maintain_source")
        validated(EmptyObject, request.data)
        source = services.withdraw_source(id, request.user)
        return Response(SourceResponseSerializer(presenters.source_summary(source)).data)


class ContextView(APIView):
    @extend_schema(responses={200: ContextResponseSerializer})
    def get(self, request, id):
        parent = selectors.context_detail(id, request.user)
        return Response(ContextResponseSerializer(presenters.context_response(parent)).data)


class EvidenceView(APIView):
    @extend_schema(responses={200: EvidenceResponseSerializer})
    def get(self, request, id):
        child = selectors.evidence_detail(id, request.user)
        return Response(EvidenceResponseSerializer(presenters.evidence_response(child)).data)


class SearchView(APIView):
    @extend_schema(request=QuerySerializer, responses={200: SearchResponseSerializer})
    def post(self, request):
        data = validated(QuerySerializer, request.data)
        result = search(data, request.user, request_id=str(uuid4()))
        return Response(SearchResponseSerializer(result).data)
