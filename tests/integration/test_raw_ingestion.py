from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from catalog.models import ContextUnit, EvidenceUnit, KnowledgeSource


pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def client_for(*permissions):
    user = get_user_model().objects.create_user("user-" + "-".join(permissions))
    user.user_permissions.set(Permission.objects.filter(content_type__app_label="catalog", codename__in=permissions))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=user).key)
    return client


def request_payload(schema="product_review", content=None, media_type="text/markdown"):
    return {
        "source": {"source_type": "wechat", "canonical_locator": "synthetic:review", "visibility": "public"},
        "preprocess": {"schema": schema, "version": 1},
        "raw": {
            "content": content or "# Laptop A\n\n## 配置\n\n16GB\n\n## 续航\n\n续航约 9 小时。",
            "media_type": media_type,
            "metadata": {"title": "合成样本", "entity_title": "Laptop A", "source_date": "2026-09-28", "author": "合成作者"},
        },
    }


@pytest.mark.parametrize("schema,content,media_type,titles", [
    ("product_review", '<div id="js_content"><h2>Laptop A</h2><p><strong>配置</strong></p>'
     '<p>16GB</p><p><strong>续航</strong></p><p>续航约 9 小时。</p></div>', "text/html", ["Laptop A"]),
    ("purchase_guide", "# 指南\n\n## 6000元\n\n### Laptop A\n\n续航好。\n\n### Laptop B\n\n游戏快。", "text/markdown",
     ["6000元", "Laptop A", "Laptop B"]),
    ("experience_case", "# 经验\n\n## 黑屏案例\n\n### 现象\n\n风扇转。\n\n### 处理与结果\n\n恢复。\n\n"
     "## 电池案例\n\n续航不足，换电池后恢复。", "text/markdown", ["黑屏案例", "电池案例"]),
])
def test_raw_api_imports_all_types_and_search_returns_complete_parent(embedder, schema, content, media_type, titles):
    client = client_for("maintain_source", "read_internal")
    data = request_payload(schema, content, media_type)
    data["raw"]["metadata"]["entity_title"] = "Laptop A"
    with patch("config.components.embedding_provider", return_value=embedder):
        imported = client.post("/api/v1/sources/raw/", data, format="json")
        assert imported.status_code == 200, imported.data
        source = KnowledgeSource.objects.get()
        assert source.source_date == date(2026, 9, 28) and source.metadata["author"] == "合成作者"
        assert list(source.contexts.order_by("ordinal").values_list("title", flat=True)) == titles
        response = client.post("/api/v1/search/", {"query": "续航", "top_k": 10}, format="json")
        assert response.status_code == 200, response.data
        assert response.data["contexts"]
        for context in response.data["contexts"]:
            parent = ContextUnit.objects.get(pk=context["context_id"])
            assert context["text"] == parent.body
            for match in context["matches"]:
                child = EvidenceUnit.objects.get(pk=match["evidence_id"])
                locator = child.locator
                assert parent.body[locator["parent_char_start"]:locator["parent_char_end"]] == child.body


def test_raw_update_and_repeated_import_keep_stable_ids(embedder):
    client = client_for("maintain_source")
    data = request_payload()
    with patch("config.components.embedding_provider", return_value=embedder):
        first = client.post("/api/v1/sources/raw/", data, format="json")
        assert first.status_code == 200, first.data
        child_ids = dict(EvidenceUnit.objects.values_list("key", "id"))
        duplicate = client.post("/api/v1/sources/raw/", data, format="json")
        assert duplicate.data["reused"] and duplicate.data["context_ids"] == first.data["context_ids"]
        data["raw"]["content"] = data["raw"]["content"].replace("9 小时", "10 小时")
        updated = client.post("/api/v1/sources/raw/", data, format="json")
        assert updated.status_code == 200 and not updated.data["reused"]
        assert updated.data["context_ids"] == first.data["context_ids"]
        assert dict(EvidenceUnit.objects.values_list("key", "id")) == child_ids


def test_raw_preprocessing_and_validation_errors_happen_before_model_setup_or_save():
    client = client_for("maintain_source")
    with patch("config.components.embedding_provider") as provider:
        for change, code in [
            ({"media_type": "application/pdf"}, "UNSUPPORTED_MEDIA_TYPE"),
            ({"content": "<script>ignored</script>", "media_type": "text/html"}, None),
            ({"metadata": {"source_date": "invalid"}}, None),
            ({"metadata": {"title": "只有文章标题"}}, "ENTITY_TITLE_REQUIRED"),
        ]:
            data = request_payload()
            data["raw"].update(change)
            response = client.post("/api/v1/sources/raw/", data, format="json")
            assert response.status_code == 400, response.data
            if code:
                assert response.data["error"]["code"] == code
        unregistered = request_payload("not_registered")
        response = client.post("/api/v1/sources/raw/", unregistered, format="json")
        assert response.data["error"]["code"] == "PREPROCESSOR_NOT_REGISTERED"
        provider.assert_not_called()
    assert not KnowledgeSource.objects.exists()


def test_raw_budget_splits_review_chunks_and_rejects_overlong_atomic_guide_section(embedder, settings):
    client = client_for("maintain_source")
    settings.PREPROCESS_MAX_INPUT_BYTES = 100
    # 评测子块只服务召回，长散热小节按预算拆分而不是拒绝。
    data = request_payload(content="# A\n\n## 散热分析\n\n" + "室温25℃，测试结果80℃。" * 40)
    with patch("config.components.embedding_provider", return_value=embedder):
        response = client.post("/api/v1/sources/raw/", data, format="json")
        assert response.status_code == 200, response.data
    assert EvidenceUnit.objects.count() > 1
    assert all(len(text.encode()) <= 100 for text in EvidenceUnit.objects.values_list("retrieval_text", flat=True))
    data = request_payload("purchase_guide", "# 指南\n\n## Laptop A\n\n### 购买建议\n\n" + "适合轻办公，不适合大型游戏。" * 40)
    data["source"]["canonical_locator"] = "synthetic:atomic"
    with patch("config.components.embedding_provider") as provider:
        response = client.post("/api/v1/sources/raw/", data, format="json")
        assert response.status_code == 400 and response.data["error"]["code"] == "SEMANTIC_UNIT_TOO_LARGE"
        provider.assert_not_called()
    assert KnowledgeSource.objects.count() == 1


def test_raw_api_checks_authentication_permissions_and_visibility_before_processing():
    assert APIClient().post("/api/v1/sources/raw/", {}, format="json").status_code == 401
    reader = client_for()
    maintainer = client_for("maintain_source")
    data = request_payload()
    with patch("config.components.preprocessors") as registry, patch("config.components.embedding_provider") as provider:
        assert reader.post("/api/v1/sources/raw/", data, format="json").status_code == 403
        data["source"]["visibility"] = "internal"
        assert maintainer.post("/api/v1/sources/raw/", data, format="json").status_code == 404
        # Registry 的构造可发生，处理不得执行。
        registry.return_value.process.assert_not_called()
        provider.assert_not_called()


def test_raw_model_failure_preserves_existing_document(embedder):
    client = client_for("maintain_source")
    data = request_payload()
    with patch("config.components.embedding_provider", return_value=embedder):
        assert client.post("/api/v1/sources/raw/", data, format="json").status_code == 200
        previous = list(EvidenceUnit.objects.values_list("body", flat=True))
        data["raw"]["content"] += "\n\n补充内容。"
        from contracts.errors import DomainError

        with patch.object(embedder, "embed_documents", side_effect=DomainError("EMBEDDING_UNAVAILABLE", "模型不可用", 502)):
            response = client.post("/api/v1/sources/raw/", data, format="json")
            assert response.status_code == 502
        assert list(EvidenceUnit.objects.values_list("body", flat=True)) == previous
