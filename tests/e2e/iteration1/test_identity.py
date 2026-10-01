import json
import os
import subprocess
import sys
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

pytestmark = pytest.mark.e2e


def command(*args):
    result = subprocess.run([sys.executable, "manage.py", *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def schema(token=None):
    request = Request(os.environ.get("KB_TEST_BASE_URL", "http://127.0.0.1:8000") + "/api/schema/", headers={"Accept": "application/vnd.oai.openapi+json"})
    if token:
        request.add_header("Authorization", "Token " + token)
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read())


def test_account_command_and_real_http_token_revocation(tmp_path):
    command("kb_init")
    command("kb_init")
    name = "e2e-" + uuid.uuid4().hex
    token_path = tmp_path / "maintainer.token"
    output = command("kb_account", "--username", name, "--permissions", "maintain_source", "--token-file", str(token_path))
    key = token_path.read_text().strip()
    assert key not in output and token_path.stat().st_mode & 0o777 == 0o600
    status, document = schema(key)
    assert status == 200 and document["openapi"].startswith("3.")
    assert "/api/v1/search/" not in document["paths"]
    command("kb_account", "--username", name + "-plain", "--permissions", "", "--token-file", str(tmp_path / "plain.token"))
    assert schema((tmp_path / "plain.token").read_text().strip())[0] == 403
    command("kb_account", "--username", name, "--revoke-token")
    assert schema(key)[0] == 401
