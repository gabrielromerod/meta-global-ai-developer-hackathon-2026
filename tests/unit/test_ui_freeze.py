"""Frozen visual-worker inputs must be local, coherent and explicitly fixture-labelled."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ui_contract_freeze_is_complete():
    for path in (
        "docs/contracts/api.md",
        "web-next/src/styles/tokens.css",
        "web-next/README.md",
        "web-next/src/fixtures/state.json",
        "web-next/src/fixtures/visits.json",
        "web-next/src/fixtures/chat.json",
    ):
        assert (ROOT / path).is_file(), f"missing frozen input: {path}"
    state = json.loads((ROOT / "web-next/src/fixtures/state.json").read_text(encoding="utf-8"))
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
    details = json.loads((ROOT / "web-next/src/fixtures/visits.json").read_text(encoding="utf-8"))
    assert set(state["attention_ids"]) <= set(details["visits"])
    assert all(
        c["power_profile"] in {"plugin_wifi", "doorbell", "battery_wifi", "import"}
        for c in state["cameras"]
    )


def test_pinned_react_ui_runtime_integrity():
    package = json.loads((ROOT / "web-next/package.json").read_text(encoding="utf-8"))
    dependencies = package["dependencies"]
    assert {
        "react",
        "react-dom",
        "lucide-react",
        "@tanstack/react-query",
        "framer-motion",
        "@react-three/fiber",
        "@react-three/drei",
        "three",
    } <= set(dependencies)
    assert "preact" not in dependencies
    assert "htm" not in dependencies
    lock = json.loads((ROOT / "web-next/package-lock.json").read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] >= 3
    for name, record in lock["packages"].items():
        if not name:
            continue
        assert record.get("version"), name
        if record.get("inBundle"):
            # npm bundles these bytes inside the nearest parent tarball, whose SRI
            # must therefore protect them. They have no separate download/SRI.
            parent = name.rsplit("/node_modules/", 1)[0]
            while lock["packages"][parent].get("inBundle"):
                parent = parent.rsplit("/node_modules/", 1)[0]
            assert lock["packages"][parent]["resolved"].startswith("https://registry.npmjs.org/")
            assert lock["packages"][parent]["integrity"].startswith("sha512-")
            continue
        assert record.get("resolved", "").startswith("https://registry.npmjs.org/"), name
        assert record.get("integrity", "").startswith("sha512-"), name
