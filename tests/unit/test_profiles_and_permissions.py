from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from catalog.hashes import digest
from catalog.policies import visible_scopes, require_permission
from catalog.profiles import load_profiles, validate_index, validate_query
from contracts.errors import DomainError

pytestmark = pytest.mark.unit
PROFILES = Path(__file__).resolve().parents[2] / "profiles/iteration1"


def test_profiles_have_stable_independent_hashes():
    config = load_profiles(PROFILES)
    assert len(config["index_profile_hash"]) == 64
    assert config["query_profile"]["index_profile_hash"] == config["index_profile_hash"]
    assert digest({"b": 2, "a": 1}) == digest({"a": 1, "b": 2})
    changed = deepcopy(config["query_profile"])
    changed["response_context_bytes"] = 1000
    validate_query(changed, config["index_profile_hash"])
    assert digest(changed) != config["query_profile_hash"]
    assert digest(config["index_profile"]) == config["index_profile_hash"]


@pytest.mark.parametrize("value", [True, "1", 2])
def test_invalid_profile_version_is_rejected(value):
    index = load_profiles(PROFILES)["index_profile"]
    index["schema_version"] = value
    with pytest.raises(DomainError):
        validate_index(index)


@pytest.mark.parametrize("staff,permissions,expected", [
    (True, set(), ["public"]), (False, {"catalog.maintain_source"}, ["public"]),
    (False, {"catalog.read_internal"}, ["public", "internal"]),
])
def test_internal_scope_depends_on_explicit_permission(staff, permissions, expected):
    actor = SimpleNamespace(is_authenticated=True, is_active=True, is_staff=staff, has_perm=permissions.__contains__)
    assert visible_scopes(actor) == expected
    with pytest.raises(DomainError) as error:
        require_permission(actor, "review_import")
    assert error.value.status == 403
