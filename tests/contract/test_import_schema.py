import pytest
from drf_spectacular.generators import SchemaGenerator

from contracts.serializers import SourceImportSerializer
from tests.samples import source_input

pytestmark = pytest.mark.contract


def test_example_matches_serializer_and_generated_openapi():
    serializer = SourceImportSerializer(data=source_input())
    assert serializer.is_valid(), serializer.errors
    schema = SchemaGenerator().get_schema(public=True)
    endpoint = schema["paths"]["/api/v1/sources/"]["post"]
    assert set(endpoint["responses"]) == {"200"}
    properties = schema["components"]["schemas"]["SourceImport"]["properties"]
    assert set(properties) == set(serializer.fields)
    assert properties["schema_version"]["type"] == "integer"
    assert "/api/v1/search/" in schema["paths"]
