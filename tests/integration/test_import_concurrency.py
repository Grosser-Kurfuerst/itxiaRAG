from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connections

from catalog.accounts import configure_account
from catalog.models import ContextUnit, EvidenceUnit, ImportJob, KnowledgeSource
from contracts.serializers import SourceImportSerializer
from ingestion.pipeline import import_text
from tests.samples import source_input

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def test_concurrent_first_imports_share_source_job_and_products():
    call_command("kb_init", stdout=StringIO())
    actor = configure_account("parallel", ["maintain_source"])
    barrier = Barrier(2)
    def submit():
        try:
            user = get_user_model().objects.get(pk=actor.pk)
            data = SourceImportSerializer(data=source_input())
            data.is_valid(raise_exception=True)
            barrier.wait(timeout=5)
            job, _ = import_text(data.validated_data, user)
            return job.pk
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        ids = [future.result(timeout=10) for future in futures]
    assert ids[0] == ids[1]
    assert KnowledgeSource.objects.count() == ImportJob.objects.count() == 1
    assert ContextUnit.objects.count() == EvidenceUnit.objects.count() == 1
