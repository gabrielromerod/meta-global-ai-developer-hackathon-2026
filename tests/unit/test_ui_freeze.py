"""Frozen visual-worker inputs must be local, coherent and explicitly fixture-labelled."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ui_contract_freeze_is_complete():
    for path in (
        "docs/contracts/api.md",
        "web/design/tokens.css",
        "web/design/README.md",
        "web/fixtures/state.json",
        "web/fixtures/visits.json",
        "web/fixtures/chat.json",
    ):
        assert (ROOT / path).is_file(), f"missing frozen input: {path}"
    state = json.loads((ROOT / "web/fixtures/state.json").read_text(encoding="utf-8"))
    assert state["contract_version"] == "vigil-ui/1"
    assert state["evidence"]["kind"] == "fixture"
    ids = {c["id"] for c in state["cameras"]}
    assert ids == {
        "front_left_duo",
        "front_right_duo",
        "doorbell",
        "porch",
        "side_left",
        "backyard_1",
        "backyard_2",
    }
    assert all(set(view["camera_ids"]) <= ids for view in state["views"])
    details = json.loads((ROOT / "web/fixtures/visits.json").read_text(encoding="utf-8"))
    assert set(state["attention_ids"]) <= set(details["visits"])
    assert all(
        c["power_profile"] in {"plugin_wifi", "doorbell", "battery_wifi", "import"}
        for c in state["cameras"]
    )


def test_vendored_ui_runtime_integrity():
    manifest = ROOT / "web/vendor/manifest.json"
    assert manifest.is_file(), "approved UI dependencies must be vendored before workers start"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for file, digest in data["files"].items():
        assert hashlib.sha256((ROOT / "web/vendor" / file).read_bytes()).hexdigest() == digest
    assert {p["name"] for p in data["packages"]} == {"preact", "htm", "lucide-static"}
