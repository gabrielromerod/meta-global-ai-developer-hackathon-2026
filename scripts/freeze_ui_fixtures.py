"""Create authored UI examples from the checked-in synthetic ledger, never live models."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from vigil.api.app import create_app
from vigil.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web-next" / "src" / "fixtures"
EVIDENCE = {
    "kind": "fixture",
    "label": "Demo data",
    "source": "authored synthetic ledger; camera names adapted to seven-camera inventory",
}
VERSION = "vigil-ui/1"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    client = TestClient(
        create_app(
            settings=Settings(
                mode="sandbox", model_api_key="invalid-freeze-fixture", meta_cache_only=True
            )
        )
    )
    scenarios = client.get("/api/scenarios").json()
    names = [
        ("front_left_duo", "Front left Duo", "plugin_wifi", "Reolink Duo Floodlight Wi-Fi"),
        ("front_right_duo", "Front right Duo", "plugin_wifi", "Reolink Duo Floodlight Wi-Fi"),
        ("doorbell", "Doorbell", "doorbell", "Reolink Wi-Fi doorbell"),
        ("porch", "Porch", "plugin_wifi", None),
        ("side_left", "Left passage", "battery_wifi", "Reolink Argus"),
        ("backyard_1", "Backyard 1", "battery_wifi", "Reolink Argus PT"),
        ("backyard_2", "Backyard 2", "battery_wifi", "Reolink Argus PT"),
    ]
    cameras = [
        {
            "id": i,
            "name": n,
            "model": m,
            "power_profile": p,
            "stream": "sub",
            "status": "not_connected",
            "source_label": "Imported clips" if p == "battery_wifi" else "Not connected",
            "hub_present": None,
            "wifi_signal_dbm": None,
            "clock_offset_s": None,
            "clip_url": None,
            "thumbnail_url": None,
        }
        for i, n, p, m in names
    ]
    mapping = {"front": "doorbell", "side_left": "side_left", "backyard": "backyard_1"}

    def adapt(value):
        if isinstance(value, dict):
            return {
                k: mapping.get(v, v)
                if k == "camera_id" and isinstance(v, str)
                else [mapping.get(x, x) for x in v]
                if k == "cameras" and isinstance(v, list)
                else adapt(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [adapt(v) for v in value]
        return value

    details = {}
    visits = []
    for scenario in scenarios["scenarios"]:
        for row in scenario["visits"]:
            detail = adapt(client.get(f"/api/visits/{row['id']}").json())
            details[row["id"]] = detail
            roles = detail["subjects"]
            visits.append(
                {
                    **adapt(row),
                    "title": scenario["title"],
                    "story": detail["first_sentence"],
                    "role_label": ", ".join(dict.fromkeys(s["role_label"] for s in roles)),
                    "role_basis": "; ".join(dict.fromkeys(s["basis_label"] for s in roles)),
                    "reason": detail["trace"]["verdict_inputs"]["floor_reason"],
                    "thumbnail_url": None,
                    "clip_url": None,
                    "evidence_kind": "fixture",
                }
            )
    events = [
        {**event, "visit_id": key} for key, detail in details.items() for event in detail["events"]
    ]
    clips = [
        {
            "id": "clip_" + v["id"],
            "visit_id": v["id"],
            "camera_id": v["cameras"][0],
            "verdict": v["verdict"],
            "clock": v["clock"],
            "t0": v["t0"],
            "t1": v["t1"],
            "title": v["story"],
            "kind": "package" if v["id"] in {"v_b", "v_bp"} else "person",
            "clip_url": None,
            "thumbnail_url": None,
            "source_label": "Authored scene",
        }
        for v in visits
    ]
    owner_windows = adapt(client.get("/api/windows").json())["windows"]
    rules = json.loads((ROOT / "config/rules.default.json").read_text())
    state = {
        "contract_version": VERSION,
        "evidence": EVIDENCE,
        "mode": "sandbox",
        "household": {"name": "Home", "avatar_url": None},
        "session": {"id": "synthetic", "start": scenarios["session_start"]},
        "cameras": cameras,
        "views": [
            {"id": i, "label": label, "camera_ids": ids}
            for i, label, ids in [
                ("overview", "Overview", [c["id"] for c in cameras]),
                ("day", "Day", [c["id"] for c in cameras]),
                ("night", "Night", [c["id"] for c in cameras]),
                ("front_garden", "Front garden", ["front_left_duo", "front_right_duo"]),
                ("porch", "Porch", ["doorbell", "porch"]),
                ("left_passage", "Left passage", ["side_left"]),
                ("backyard", "Backyard", ["backyard_1", "backyard_2"]),
            ]
        ]
        + [
            {"id": "camera_" + c["id"], "label": c["name"], "camera_ids": [c["id"]]}
            for c in cameras
        ],
        "summary": {
            "camera_events": None,
            "on_property": None,
            "visits": len(visits),
            "needs_attention": sum(v["verdict"] == "needs_attention" for v in visits),
            "street_events": None,
            "note": "Camera prefilter counts are not available for this recording.",
        },
        "visits": visits,
        "attention_ids": ["v_c", "v_b", "v_ap", "v_bp"],
        "notifications": [
            {
                "id": "n_" + v["id"],
                "visit_id": v["id"],
                "verdict": v["verdict"],
                "story": v["story"],
                "clock": v["clock"],
                "thumbnail_url": None,
                "unread": True,
            }
            for v in visits
            if v["verdict"] in {"needs_attention", "noteworthy"}
        ],
        "clips": clips,
        "events": events,
        "rules": rules if isinstance(rules, list) else rules.get("rules", []),
        "protected_objects": json.loads(
            (ROOT / "demo/synthetic/tables/protected_objects.json").read_text()
        ),
        "benchmark": {"measured": False, "metrics": [], "note": "No field benchmark recorded."},
        "owner": {
            "enabled": False,
            "reason": "Owner-only on the home box",
            "checkin_duration_s": 120,
            "windows": owner_windows,
        },
        "capabilities": {
            "ask_home": True,
            "household_messaging": "local_mock",
            "snapshot": False,
            "recording": False,
            "owner": False,
        },
    }
    chat = {
        "contract_version": VERSION,
        "evidence": EVIDENCE,
        "threads": [
            {
                "id": "ask-home",
                "title": "Ask your home",
                "kind": "assistant",
                "note": "Answers use the cached visit ledger.",
                "messages": [],
            },
            {
                "id": "household",
                "title": "Household",
                "kind": "local_mock",
                "note": "Local demo thread; messages stay in this browser.",
                "messages": [],
            },
        ],
    }
    poses = [
        ((3.2, 2.6, 0), (2, 0, -7)),
        ((-3.2, 2.6, 0), (-2, 0, -7)),
        ((0, 1.5, -0.1), (0, 0, -3)),
        ((0, 2.6, -0.1), (0, 0, -3)),
        ((3.3, 2.4, 1), (4, 0, 7)),
        ((3, 2.4, 7.1), (1, 0, 12)),
        ((-3, 2.4, 7.1), (-1, 0, 12)),
    ]
    twin = {
        "contract_version": VERSION,
        "evidence": EVIDENCE,
        "generic_massing": True,
        "ground": {"min": [-9, -10], "max": [9, 14]},
        "site_plan": {
            "boxes": [
                {"id": "house", "kind": "building", "min": [-3, 0], "max": [3, 7], "h": 3},
                {
                    "id": "right_trees",
                    "kind": "tree_barrier",
                    "min": [-6, 0],
                    "max": [-5, 11],
                    "h": 3,
                },
            ]
        },
        "cameras": [
            {
                **c,
                "position": p,
                "look_at": aim,
                "width": 1920 if "duo" in c["id"] else 1280,
                "height": 720,
                "hfov_deg": 90,
                "vfov_deg": 55,
                "range_m": 8,
            }
            for c, (p, aim) in zip(cameras, poses, strict=True)
        ],
        "blind_regions": [
            {
                "id": "shed_back",
                "name": "unobserved backyard area",
                "polygon_m": [[4.1, 9], [7.3, 9], [7.3, 11.2], [4.1, 11.2]],
            }
        ],
        "coverage": [],
        "protected_objects": [],
        "glb_url": None,
    }
    for name, value in [
        ("state", state),
        ("visits", {"contract_version": VERSION, "evidence": EVIDENCE, "visits": details}),
        ("chat", chat),
        ("twin", twin),
    ]:
        (OUT / f"{name}.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
