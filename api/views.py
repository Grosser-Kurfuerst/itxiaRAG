from dataclasses import asdict

from rest_framework.response import Response
from rest_framework.views import APIView

from api.operations import run_recommend, run_search
from catalog.policies import require_permission
from config import components
from contracts.products import RecommendInput
from contracts.query import QueryInput
from contracts.requests import parse_model
from contracts.serializers import RawSourceImportSerializer, SourceImportSerializer, import_dtos, import_raw_dtos
from ingestion.pipeline import import_processed, preprocess_raw


def validated(serializer_class, data, context=None):
    serializer = serializer_class(data=data, context=context or {})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class SourceImportView(APIView):
    def post(self, request):
        require_permission(request.user, "maintain_source")
        source, document = import_dtos(validated(SourceImportSerializer, request.data))
        result = import_processed(source, document,
                                  embedder=components.embedding_provider(), store=components.document_store())
        return Response(asdict(result))


class RawSourceImportView(APIView):
    def post(self, request):
        require_permission(request.user, "maintain_source")
        source, raw, schema, version = import_raw_dtos(validated(RawSourceImportSerializer, request.data))
        document = preprocess_raw(source, raw, schema, version, registry=components.preprocessors())
        result = import_processed(source, document,
                                  embedder=components.embedding_provider(), store=components.document_store())
        return Response(asdict(result))


class SearchView(APIView):
    def post(self, request):
        return Response(run_search(parse_model(QueryInput, request.data), request.user))


class ProductRecommendView(APIView):
    def post(self, request):
        return Response(run_recommend(parse_model(RecommendInput, request.data), request.user))
