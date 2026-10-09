from datetime import date
from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command

from catalog.models import EvidenceUnit, KnowledgeSource
from tests.wechat_capture import build_capture


pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def capture(tmp_path):
    return build_capture(tmp_path)


def test_capture_command_imports_reviews_and_guides_then_reimport_reuses(capture, embedder):
    root, manifest = capture
    actor = get_user_model().objects.create_user("wechat-maintainer")
    actor.user_permissions.set(Permission.objects.filter(
        content_type__app_label="catalog", codename__in=["maintain_source", "read_internal"]))
    first, repeated = StringIO(), StringIO()
    with patch("config.components.embedding_provider", return_value=embedder):
        call_command("import_wechat", manifest=str(manifest), capture=str(root), username=actor.username, stdout=first)
        ids = list(EvidenceUnit.objects.order_by("id").values_list("id", flat=True))
        call_command("import_wechat", manifest=str(manifest), capture=str(root), username=actor.username,
                     stdout=repeated)
    assert "imported=2" in first.getvalue() and "reused=2" in repeated.getvalue()
    assert "skipped=1" in first.getvalue() and "unregistered=1" in first.getvalue()
    assert list(EvidenceUnit.objects.order_by("id").values_list("id", flat=True)) == ids
    review, guide = KnowledgeSource.objects.order_by("canonical_locator")
    assert review.source_type == guide.source_type == "wechat"
    assert review.canonical_locator == "mp:MzA5MDAwMDAwMA==:2650000001:2"
    assert review.visibility == "internal" and guide.visibility == "public"
    assert review.document_schema == "product_review" and guide.document_schema == "purchase_guide"
    assert review.source_date == date(2026, 9, 28) and guide.source_date is None
    assert review.source_url.endswith("&sn=abc123") and guide.source_url == "https://mp.weixin.qq.com/s/AbC-123_x"
    assert review.metadata["wechat"] == {"account": "合成评测室", "author": "合成作者", "classified_by": "manifest"}
    assert list(review.contexts.values_list("title", flat=True)) == ["合成笔记本 A"]
