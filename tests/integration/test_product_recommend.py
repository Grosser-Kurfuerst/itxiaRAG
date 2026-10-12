from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from catalog.models import ContextUnit
from catalog.storage import DjangoDocumentStore
from contracts.products import PORTS
from contracts.serializers import SourceImportSerializer, import_dtos
from ingestion.pipeline import import_processed
from products.importing import import_specs

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def import_review(embedder, title, source_date, chunks, visibility="public"):
    """合成单机评测；chunks 为 (正文, 栏目名列表)。"""
    payload = {
        "source": {"source_type": "manual", "canonical_locator": f"example:{title}", "visibility": visibility},
        "document": {"title": f"{title} 评测", "document_schema": "product_review", "source_date": source_date,
                     "contexts": [{"key": "review", "title": title, "body": "\n".join(body for body, _ in chunks),
                                   "children": [{"key": f"chunk-{number}", "body": body, "metadata": {"sections": sections}}
                                                for number, (body, sections) in enumerate(chunks, 1)]}]},
    }
    serializer = SourceImportSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    import_processed(*import_dtos(serializer.validated_data), embedder=embedder, store=DjangoDocumentStore())


def spec(key, **fields):
    return {"key": key, "brand": key.split()[0], "ports": dict.fromkeys(PORTS, False), **fields}


@pytest.fixture
def catalog(embedder):
    import_review(embedder, "联想 游戏本", "2026-09-01", [
        ("配置为 RTX 5070。", ["配置"]), ("优点：性能释放强。", ["优点"]), ("购买建议：值得买。", ["购买建议"]),
        ("购买建议续：屏幕测试数据。", ["购买建议"]), ("电池测试约 6 小时。", ["续航"])])
    import_review(embedder, "华为 轻薄本", "2026-08-01", [
        ("机身很轻。", ["外观"]), ("日常续航超过 12 小时。", ["续航"])])
    import_review(embedder, "雷蛇 内部样机", "2026-10-01", [("内部资料。", ["总结"])], visibility="internal")
    report = import_specs([
        spec("联想 游戏本", price_cny=9999, weight_kg=2.4, has_dgpu=True, gpu="RTX 5070", is_gaming=True),
        spec("华为 轻薄本", price_cny=6999, weight_kg=1.2, has_dgpu=False, is_gaming=False),
        spec("雷蛇 内部样机", price_cny=8999, weight_kg=1.5, has_dgpu=False),
    ])
    assert not report.failed


def client_for(permissions=()):
    user = get_user_model().objects.create_user(f"reader-{'-'.join(permissions)}")
    user.user_permissions.set(Permission.objects.filter(codename__in=permissions))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=user).key)
    return client


def recommend(client, embedder, payload):
    with patch("config.components.embedding_provider", return_value=embedder):
        return client.post("/api/v1/products/recommend/", payload, format="json")


def keys(response):
    return [product["key"] for product in response.data["products"]]


def test_empty_request_lists_visible_laptops_newest_first(catalog, embedder):
    assert APIClient().post("/api/v1/products/recommend/", {}, format="json").status_code == 401
    response = recommend(client_for(), embedder, {})
    assert response.status_code == 200, response.data
    assert keys(response) == ["联想 游戏本", "华为 轻薄本"]
    assert keys(recommend(client_for(["read_internal"]), embedder, {}))[0] == "雷蛇 内部样机"


def test_preference_ranks_candidates_and_attaches_review_text(catalog, embedder):
    response = recommend(client_for(), embedder, {"conditions": {"price_max": 10000}, "preference": "续航"})
    assert keys(response) == ["华为 轻薄本", "联想 游戏本"]
    first = response.data["products"][0]
    assert first["spec"]["weight_kg"] == 1.2 and "evidence" not in first["spec"]
    assert first["review"]["source"]["source_date"] == date(2026, 8, 1)
    assert first["review"]["source"]["id"] == str(ContextUnit.objects.get(title="华为 轻薄本").source_id)
    assert first["review"]["highlights"][0]["text"] == "日常续航超过 12 小时。"
    assert [item["text"] for item in first["review"]["conclusions"]] == ["日常续航超过 12 小时。"]  # 无结论栏目，取最后一块

    gaming = response.data["products"][1]["review"]
    assert [item["sections"] for item in gaming["conclusions"]] == [["优点"], ["购买建议"]]


def test_conditions_filter_and_report_unknown_or_diagnostics(catalog, embedder):
    client = client_for()
    response = recommend(client, embedder, {"conditions": {"gpu_in": ["rtx5070"], "battery_min": 5}})
    assert response.data["result_status"] == "no_result"
    assert response.data["unknown"] == {"battery_hours": 1}
    assert response.data["diagnostics"] == {"total": 2, "satisfied": {"gpu_in": 1, "battery_min": 0}}

    response = recommend(client, embedder, {"conditions": {"gpu_in": ["RTX 5070"], "brands": ["联想"]}, "top_k": 1})
    assert keys(response) == ["联想 游戏本"] and response.data["diagnostics"] is None


def test_unknown_options_and_fields_are_rejected(catalog, embedder):
    client = client_for()
    response = recommend(client, embedder, {"conditions": {"gpu_in": ["RTX 4090"]}})
    assert response.status_code == 400 and "RTX 5070" in str(response.data)
    response = recommend(client, embedder, {"conditions": {"brands": ["雷蛇"]}})  # 内部机型的品牌对普通用户不可选
    assert response.status_code == 400 and "可选：华为、联想" in str(response.data)
    assert recommend(client_for(["read_internal"]), embedder, {"conditions": {"brands": ["雷蛇"]}}).status_code == 200
    assert recommend(client, embedder, {"conditions": {"thin_light": True}}).status_code == 400
    assert recommend(client, embedder, {"top_k": 21}).status_code == 400


def test_preference_search_is_limited_to_candidate_reviews(catalog, embedder):
    # 不限定范围时，“续航”的第一名是华为轻薄本，只取 1 个父段会让游戏本没有命中子块。
    response = recommend(client_for(), embedder, {"conditions": {"is_gaming": True}, "preference": "续航"})
    assert keys(response) == ["联想 游戏本"]
    assert response.data["products"][0]["review"]["highlights"]
