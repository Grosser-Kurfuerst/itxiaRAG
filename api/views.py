from dataclasses import asdict

from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.policies import require_permission
from config import components
from contracts.query import QuerySerializer
from contracts.serializers import RawSourceImportSerializer, SourceImportSerializer, import_dtos, import_raw_dtos
from ingestion.pipeline import import_processed, preprocess_raw
from retrieval.service import search


def validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class SourceImportView(APIView):
    def post(self, request):
        require_permission(request.user, "maintain_source")
        source, document = import_dtos(validated(SourceImportSerializer, request.data))
        result = import_processed(source, document, request.user,
                                  embedder=components.embedding_provider(), store=components.document_store())
        return Response(asdict(result))


class RawSourceImportView(APIView):
    def post(self, request):
        require_permission(request.user, "maintain_source")
        source, raw, schema, version = import_raw_dtos(validated(RawSourceImportSerializer, request.data))
        document = preprocess_raw(source, raw, schema, version, request.user, registry=components.preprocessors())
        result = import_processed(source, document, request.user,
                                  embedder=components.embedding_provider(), store=components.document_store())
        return Response(asdict(result))


class SearchView(APIView):
    def post(self, request):
        data = validated(QuerySerializer, request.data)
        embedder = components.embedding_provider()
        result = search(data, request.user, collector=components.recall_collector(embedder),
                        pipeline=components.post_recall_pipeline(),
                        reader=components.context_reader(), embedding_space=embedder.space_id,
                        candidate_limit=settings.RETRIEVAL_CANDIDATE_LIMIT)
        return Response(result)
