from io import StringIO
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from catalog.accounts import configure_account
from catalog.hashes import digest
from catalog.models import KnowledgeSource, ImportJob, ContextUnit, EvidenceUnit, RetrievalSettings
from catalog.policies import visible_scopes
from catalog.profiles import active_profiles
from contracts.errors import DomainError

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_init_is_idempotent_and_refuses_configuration_overwrite():
    call_command("kb_init", stdout=StringIO())
    before = RetrievalSettings.objects.get().index_profile_hash
    call_command("kb_init", stdout=StringIO())
    assert RetrievalSettings.objects.count() == 1
    config = active_profiles()
    assert config.index_profile_hash == before == digest(config.index_profile)
    system = get_user_model().objects.get(username="kb-system")
    assert not system.has_usable_password() and not system.is_superuser and not system.is_staff
    assert not Token.objects.filter(user=system).exists()
    assert set(system.user_permissions.values_list("codename", flat=True)) == {"maintain_source", "read_internal", "review_import"}
    config.query_profile_hash = "corrupt"
    config.save()
    with pytest.raises(CommandError):
        call_command("kb_init", stdout=StringIO())
    assert RetrievalSettings.objects.get().query_profile_hash == "corrupt"


def test_tokens_scope_and_schema_access(tmp_path):
    call_command("kb_init", stdout=StringIO())
    token_file = tmp_path / "maintainer.token"
    maintainer = configure_account("maintainer", ["maintain_source"], token_file)
    assert token_file.stat().st_mode & 0o777 == 0o600
    assert not maintainer.has_usable_password()
    client = APIClient()
    assert client.get("/api/schema/").status_code == 401
    client.credentials(HTTP_AUTHORIZATION=f"Token {token_file.read_text().strip()}")
    assert client.get("/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json").status_code == 200
    member = configure_account("member", ["read_internal"], tmp_path / "member.token")
    plain = configure_account("plain", [], tmp_path / "plain.token")
    plain.is_staff = True
    plain.save()
    assert visible_scopes(plain) == ["public"] and visible_scopes(member) == ["public", "internal"]
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.get(user=plain).key}")
    assert client.get("/api/schema/").status_code == 403
    with pytest.raises(DomainError):
        configure_account("maintainer", ["read_internal"])
    with pytest.raises(DomainError):
        configure_account("kb-system", [], tmp_path / "system.token")
    old_key = token_file.read_text().strip()
    configure_account("maintainer", revoke=True)
    client.credentials(HTTP_AUTHORIZATION=f"Token {old_key}")
    assert client.get("/api/schema/").status_code == 401
    configure_account("maintainer", token_file=tmp_path / "rotated.token")
    assert (tmp_path / "rotated.token").read_text().strip() != old_key


def test_postgres_constraints_reject_invalid_storage():
    assert connection.vendor == "postgresql"
    user = get_user_model().objects.create_user(username="constraints")
    source_data = dict(source_type="manual", canonical_locator="manual:constraints", visibility="public", authorization_status="confirmed", authorization_note="合成", created_by=user)
    source = KnowledgeSource.objects.create(**source_data)
    with pytest.raises(IntegrityError), transaction.atomic():
        KnowledgeSource.objects.create(**source_data)
    with pytest.raises(IntegrityError), transaction.atomic():
        KnowledgeSource.objects.filter(pk=source.pk).update(visibility="secret")
    job = ImportJob.objects.create(source=source, created_by=user, input_text="合成", title="约束", format="txt", schema_version=1, document_schema="generic_note")
    context = ContextUnit.objects.create(build=job, ordinal=1, title="约束", body="合成")
    with pytest.raises(IntegrityError), transaction.atomic():
        ContextUnit.objects.create(build=job, ordinal=1, title="重复", body="合成")
    with pytest.raises(IntegrityError), transaction.atomic():
        EvidenceUnit.objects.create(context=context, ordinal=0, knowledge_type="concept", evidence_role="source_statement", context_role="main")
    with pytest.raises(IntegrityError), transaction.atomic():
        EvidenceUnit.objects.create(context=context, ordinal=1, knowledge_type="bad", evidence_role="source_statement", context_role="main")
    with pytest.raises(IntegrityError), transaction.atomic():
        RetrievalSettings.objects.create(id=2)
    with pytest.raises(IntegrityError), transaction.atomic():
        KnowledgeSource.objects.filter(pk=source.pk).update(current_build_id=uuid.uuid4())
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
