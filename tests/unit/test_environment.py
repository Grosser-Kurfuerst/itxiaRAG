import pytest
from django.core.exceptions import ImproperlyConfigured

from config.environment import boolean, bounded_float, required

pytestmark = pytest.mark.unit


def test_missing_secret_fails_without_echoing_value(monkeypatch):
    monkeypatch.delenv("MISSING_TEST_SECRET", raising=False)
    with pytest.raises(ImproperlyConfigured, match="MISSING_TEST_SECRET"):
        required("MISSING_TEST_SECRET")


def test_invalid_boolean_is_not_silently_enabled(monkeypatch):
    monkeypatch.setenv("DEBUG", "unexpected-private-value")
    with pytest.raises(ImproperlyConfigured) as caught:
        boolean("DEBUG")
    assert "unexpected-private-value" not in str(caught.value)


@pytest.mark.parametrize('value, expected', [(None, None), ('', None), ('  ', None),
                                             ('-1', -1), ('0.6', .6), ('1', 1)])
def test_optional_cosine_config_and_bounds(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv('RETRIEVAL_MIN_COSINE', raising=False)
    else:
        monkeypatch.setenv('RETRIEVAL_MIN_COSINE', value)
    assert bounded_float('RETRIEVAL_MIN_COSINE', None, -1, 1) == expected


@pytest.mark.parametrize('value', ['nan', 'inf', '-inf', '-1.01', '1.01', 'private-invalid'])
def test_invalid_cosine_config_does_not_echo_value(monkeypatch, value):
    monkeypatch.setenv('RETRIEVAL_MIN_COSINE', value)
    with pytest.raises(ImproperlyConfigured) as caught:
        bounded_float('RETRIEVAL_MIN_COSINE', None, -1, 1)
    assert str(caught.value).startswith('环境变量 RETRIEVAL_MIN_COSINE ')
    assert value not in str(caught.value)


def test_bm25_config_defaults_to_zero_and_rejects_negative_values(monkeypatch):
    monkeypatch.delenv('RETRIEVAL_MIN_BM25', raising=False)
    assert bounded_float('RETRIEVAL_MIN_BM25', 0.0, 0) == 0.0
    monkeypatch.setenv('RETRIEVAL_MIN_BM25', '-1')
    with pytest.raises(ImproperlyConfigured):
        bounded_float('RETRIEVAL_MIN_BM25', 0.0, 0)
