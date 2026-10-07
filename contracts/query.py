from rest_framework import serializers

from contracts.serializers import StrictSerializer, TextField


class FiltersSerializer(StrictSerializer):
    source_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=50, required=False)


class QuerySerializer(StrictSerializer):
    query = TextField(max_length=2000)
    filters = FiltersSerializer(default=dict)
    top_k = serializers.IntegerField(min_value=1, max_value=20, default=5)
