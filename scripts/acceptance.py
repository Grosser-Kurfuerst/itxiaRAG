"""运行真实 HTTP 验收。STEP 仅选择范围，不改变应用行为。"""
import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.release import IMPLEMENTED_STEP


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=[f"S{i}" for i in range(7)], default="S6")
    args = parser.parse_args()
    step = int(args.step[1:])
    if step > IMPLEMENTED_STEP:
        parser.error(f"当前仅完成 S{IMPLEMENTED_STEP}，不能验收 {args.step}")
    report = Path(os.environ.get("KB_REPORT_DIR", "/tmp/itxia-acceptance"))
    report.mkdir(parents=True, exist_ok=True)
    print(f"Python={platform.python_version()} implemented=S{IMPLEMENTED_STEP} requested={args.step}", flush=True)
    print(f"report={report / (args.step + '.xml')}", flush=True)
    return subprocess.call([
        sys.executable, "-m", "pytest", "tests/e2e/iteration1", "-q",
        "--step", args.step, "--junitxml", str(report / (args.step + ".xml")),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
