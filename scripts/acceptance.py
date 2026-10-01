"""运行真实 HTTP 验收。STEP 仅选择范围，不改变应用行为。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from importlib.metadata import version

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.release import IMPLEMENTED_STEP


def environment_report():
    root = Path(__file__).resolve().parents[1]
    fingerprint = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        fingerprint.update(str(path.relative_to(root)).encode())
        fingerprint.update(path.read_bytes())
    report = {"source_sha256": fingerprint.hexdigest(), "python": platform.python_version(),
              "django": version("Django"), "drf": version("djangorestframework"),
              "implemented_step": f"S{IMPLEMENTED_STEP}"}
    if IMPLEMENTED_STEP >= 1:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        import django
        django.setup()
        from catalog.profiles import active_profiles
        from django.db import connection
        profile = active_profiles()
        report.update(index_profile_hash=profile.index_profile_hash,
                      query_profile_hash=profile.query_profile_hash)
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            report["postgresql"] = cursor.fetchone()[0]
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=[f"S{i}" for i in range(7)], default="S6")
    args = parser.parse_args()
    step = int(args.step[1:])
    if step > IMPLEMENTED_STEP:
        parser.error(f"当前仅完成 S{IMPLEMENTED_STEP}，不能验收 {args.step}")
    report = Path(os.environ.get("KB_REPORT_DIR", "/tmp/itxia-acceptance"))
    report.mkdir(parents=True, exist_ok=True)
    metadata = environment_report()
    metadata["requested_step"] = args.step
    (report / (args.step + "-environment.json")).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Python={platform.python_version()} implemented=S{IMPLEMENTED_STEP} requested={args.step}", flush=True)
    print(f"report={report / (args.step + '.xml')}", flush=True)
    files = ["tests/e2e/iteration1/test_service.py"]
    if step >= 1:
        files.append("tests/e2e/iteration1/test_identity.py")
    if step >= 2:
        files.append("tests/e2e/iteration1/test_import.py")
    if step >= 3:
        files.append("tests/e2e/iteration1/test_publish.py")
    if step >= 4:
        files.append("tests/e2e/iteration1/test_search.py")
    if step >= 5:
        files.append("tests/e2e/iteration1/test_auto_release.py")
    if step >= 6:
        # 最终验收含完整离线与数据库故障/并发矩阵，不能仅凭 HTTP 主链路声明通过。
        files = ["tests/unit", "tests/contract", "tests/integration", *files,
                 "tests/e2e/iteration1/test_demo.py"]
    return subprocess.call([
        sys.executable, "-m", "pytest", *files, "-q",
        "--step", args.step, "--junitxml", str(report / (args.step + ".xml")),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
