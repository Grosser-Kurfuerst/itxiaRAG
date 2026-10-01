import json
import os
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def command(*args, expected=0):
    result = subprocess.run([sys.executable, "manage.py", *map(str, args)],
                            capture_output=True, text=True)
    assert result.returncode == expected, (result.returncode, result.stdout, result.stderr)
    return result.stdout


def request(method, path, token=None, data=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Token " + token
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(os.environ.get("KB_TEST_BASE_URL", "http://127.0.0.1:8000") + path,
                  method=method, data=body, headers=headers)
    try:
        response = urlopen(req, timeout=10)
    except HTTPError as exc:
        response = exc
    with response:
        raw = response.read()
        try:
            document = json.loads(raw)
        except ValueError:
            document = None
        return response.status, document


def account(name, permissions, directory):
    file = directory / f"{name}.token"
    command("kb_account", "--username", name, "--permissions", permissions,
            "--token-file", file)
    return file.read_text().strip()
