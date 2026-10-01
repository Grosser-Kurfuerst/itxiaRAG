from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connections

from catalog.accounts import configure_account
from catalog.models import KnowledgeSource
from catalog.services import publish_build, review_job
from contracts.errors import DomainError
from contracts.serializers import SourceImportSerializer
from ingestion.pipeline import import_text
from tests.samples import source_input

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def test_concurrent_publish_has_one_winner_and_no_partial_switch():
    call_command("kb_init", stdout=StringIO())
    actor = configure_account("parallel", ["maintain_source", "review_import"])
    jobs = []
    for text in ["候选 A", "候选 B"]:
        data = SourceImportSerializer(data=source_input(input_text=text))
        data.is_valid(raise_exception=True)
        job, _ = import_text(data.validated_data, actor)
        review_job(job.pk, "approved", "合成并发验收", actor)
        jobs.append(job)
    barrier = Barrier(2)
    def publish(job):
        try:
            user = get_user_model().objects.get(pk=actor.pk)
            barrier.wait(timeout=5)
            try:
                publish_build(job.pk, user)
                return "published", job.pk
            except DomainError as exc:
                return exc.code, job.pk
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, jobs))
    assert sorted(code for code, _ in results) == ["BUILD_CONFLICT", "published"]
    winner = next(id for code, id in results if code == "published")
    assert KnowledgeSource.objects.get().current_build_id == winner
    assert all(job.contexts.count() == 1 for job in jobs)
