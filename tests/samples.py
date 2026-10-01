import json
from pathlib import Path


def source_input(**changes):
    root = Path(__file__).resolve().parents[1] / "fixtures/iteration1"
    value = json.loads((root / "basic.json").read_text())
    value["input_text"] = (root / "basic.txt").read_text()
    value.update(changes)
    return value
