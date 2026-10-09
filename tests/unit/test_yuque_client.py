"""快照故障边界以替身验证，不开 socket。"""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from contracts.errors import DomainError
from sources.yuque.client import YuqueDocRef, YuqueOpenApiClient, YuqueSnapshotClient


@pytest.fixture
def ref():
    return YuqueDocRef(1, "help", "install", "合成安装", (), datetime(2025, 11, 23, tzinfo=timezone.utc))


def test_snapshot_read_failure_removes_stale_body_and_keeps_successful_bodies(tmp_path, ref):
    client = YuqueOpenApiClient("http://unused/api/v2", "synthetic-secret", "synthetic", interval=0)
    metadata = {"id": 1, "slug": "install", "title": ref.title,
                "content_updated_at": ref.content_updated_at.isoformat()}
    with patch.object(client, "_get", side_effect=[{"data": []}, {"data": [metadata]}]):
        assert client.list_docs("help") == [ref]
    target = tmp_path / "help"
    target.mkdir()
    (target / "install.md").write_text("旧正文", encoding="utf-8")
    failure = DomainError("YUQUE_RATE_LIMITED", "合成限流")
    with patch.object(client, "read_markdown", side_effect=failure):
        assert client.save_snapshot(tmp_path, [ref]) == {"help/install": failure}
    assert not (target / "install.md").exists()
    assert YuqueSnapshotClient(tmp_path).list_docs("help") == [ref]
    with patch.object(client, "read_markdown", return_value="本轮合成正文"):
        assert client.save_snapshot(tmp_path, [ref]) == {}
    assert YuqueSnapshotClient(tmp_path).read_markdown(ref) == "本轮合成正文"
    assert json.loads((target / "docs.json").read_text()) == {"data": [metadata]}


def test_snapshot_write_failure_terminates_without_exposing_path_or_token(tmp_path):
    client = YuqueOpenApiClient("http://unused/api/v2", "synthetic-secret", "synthetic", interval=0)
    with patch.object(client, "_get", side_effect=[{"data": []}, {"data": []}]):
        client.list_docs("help")
    directory = tmp_path / "file"
    directory.write_text("blocking file")
    with pytest.raises(DomainError) as error:
        client.save_snapshot(directory, [])
    assert error.value.code == "SNAPSHOT_WRITE_FAILED"
    assert "synthetic-secret" not in str(error.value)
