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


def tutorial_payload(content, *, visibility="public"):
    return {
        "source": {
            "source_type": "yuque", "canonical_locator": "synthetic:yuque-tutorial", "visibility": visibility,
        },
        "preprocess": {"schema": "tutorial", "version": 1},
        "raw": {
            "content": content, "media_type": "text/x-yuque-markdown",
            "metadata": {"title": "合成安装教程", "source_date": "2025-11-23", "collection_path": ["合成目录"]},
        },
    }


def assert_matches_locate_original_text(response):
    for context in response.data["contexts"]:
        parent = ContextUnit.objects.get(pk=context["context_id"])
        assert context["text"] == parent.body
        for match in context["matches"]:
            child = EvidenceUnit.objects.get(pk=match["evidence_id"])
            locator = child.locator
            assert parent.body[locator["parent_char_start"]:locator["parent_char_end"]] == child.body


def test_synthetic_install_tutorial_matches_manual_acceptance_and_duplicate_is_reused(embedder):
    client = client_for("maintain_source")
    # 分阶段方案 3.3 的手工合成样本，短准备篇合并后沿用安装篇标题。
    content = (
        "# 合成安装教程\n\n## 准备篇\n\n"
        "准备一个 8GB 以上的 U 盘，并备份 C 盘中的个人文件。下载官方镜像后使用写盘工具制作启动盘，"
        "写盘会清空 U 盘中原有的数据。\n\n## 安装篇\n\n### 一、进入装机盘\n\n"
        "开机时连续按 F12，在启动菜单中选择 U 盘。\n\n### 二、开始安装\n\n"
        ":::warning\n删除分区前确认已经备份数据。\n:::\n\n"
        "选择自定义安装，截至 2025 年该选项仍位于第二页。"
    )
    data = tutorial_payload(content)
    with patch("config.components.embedding_provider", return_value=embedder):
        imported = client.post("/api/v1/sources/raw/", data, format="json")
        assert imported.status_code == 200, imported.data
        source = KnowledgeSource.objects.get()
        assert source.document_schema == "tutorial" and source.source_date == date(2025, 11, 23)
        assert source.metadata["collection_path"] == ["合成目录"]
        parent = ContextUnit.objects.get()
        assert parent.title == "安装篇"
        assert parent.warnings == [
            "【警告】\n删除分区前确认已经备份数据。",
            "含时间限定表述‘截至 2025 年’，请结合来源日期判断是否仍适用",
        ]
        response = client.post("/api/v1/search/", {"query": "开机按什么键选择 U 盘", "top_k": 5}, format="json")
        assert response.status_code == 200, response.data
        context, = response.data["contexts"]
        assert context["title"] == "安装篇" and context["source"]["document_schema"] == "tutorial"
        assert context["warnings"] == parent.warnings
        assert_matches_locate_original_text(response)
        child_ids = list(EvidenceUnit.objects.order_by("ordinal").values_list("id", flat=True))
        duplicate = client.post("/api/v1/sources/raw/", data, format="json")
        assert duplicate.status_code == 200 and duplicate.data["reused"]
        assert duplicate.data["context_ids"] == imported.data["context_ids"]
        assert list(EvidenceUnit.objects.order_by("ordinal").values_list("id", flat=True)) == child_ids


def test_long_tutorial_returns_section_paths_global_and_parent_warnings_and_prefixes(embedder):
    client = client_for("maintain_source")
    content = (
        ":::warning\n全文操作前先备份。\n:::\n\n# 合成安装教程\n\n## 准备篇\n\n"
        + "准备启动盘和独立的备份盘。" * 20
        + "\n\n## 安装篇\n\n### 三、开始安装\n\n"
        + "选择安装分区前仔细确认目标磁盘。" * 120
        + "\n\n:::warning\n删除分区前确认已经备份数据。\n:::\n\n"
        + "截至 2025 年，安装选项仍位于第二页。\n\n![](synthetic.png)\n\n"
        + "### 四、安装完成\n\n" + "移除启动盘再重新启动电脑。" * 120
    )
    with patch("config.components.embedding_provider", return_value=embedder), \
            patch.object(embedder, "embed_documents", wraps=embedder.embed_documents) as embed:
        imported = client.post("/api/v1/sources/raw/", tutorial_payload(content), format="json")
        assert imported.status_code == 200, imported.data
        source = KnowledgeSource.objects.get()
        assert source.warnings == ["原文含未转写的截图，操作界面以原文链接为准", "【警告】\n全文操作前先备份。"]
        parents = list(source.contexts.order_by("ordinal"))
        assert [parent.title for parent in parents] == ["准备篇", "安装篇 > 三、开始安装", "安装篇 > 四、安装完成"]
        installing = parents[1]
        assert installing.metadata["omitted_images"] == 1 and "未提供文字说明" not in installing.body
        assert len(installing.warnings) == 2 and "删除分区前" in installing.warnings[0]
        assert "截至 2025 年" in installing.warnings[1]
        children = list(EvidenceUnit.objects.order_by("context__ordinal", "ordinal"))
        assert embed.call_args.args[0] == [child.retrieval_text for child in children]
        assert all("合成目录 > 合成安装教程\n" in child.retrieval_text for child in children)
        assert any("-part-" in child.key for child in children)
        response = client.post("/api/v1/search/", {"query": "选择安装分区", "top_k": 10}, format="json")
    assert response.status_code == 200, response.data
    context = next(c for c in response.data["contexts"] if c["title"] == "安装篇 > 三、开始安装")
    assert context["warnings"] == source.warnings + installing.warnings
    assert "全文操作前先备份" in " ".join(context["warnings"])
    assert_matches_locate_original_text(response)


def test_internal_tutorial_is_only_visible_to_authorized_token_accounts(embedder):
    maintainer = client_for("maintain_source", "read_internal")
    reader = client_for()
    data = tutorial_payload("## 安装篇\n\n安装过程中先备份数据。", visibility="internal")
    with patch("config.components.embedding_provider", return_value=embedder):
        imported = maintainer.post("/api/v1/sources/raw/", data, format="json")
        assert imported.status_code == 200, imported.data
        response = reader.post("/api/v1/search/", {"query": "安装", "top_k": 5}, format="json")
        assert response.status_code == 200 and response.data["contexts"] == []
        authorized = maintainer.post("/api/v1/search/", {"query": "安装", "top_k": 5}, format="json")
        assert authorized.status_code == 200 and len(authorized.data["contexts"]) == 1
        assert authorized.data["contexts"][0]["source"]["document_schema"] == "tutorial"
