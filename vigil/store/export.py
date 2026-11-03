"""`vigil export`: the demo bundle (FR-027) and its loader for the sandbox (spec 5.2).

Bundle layout (every file deterministic for the same inputs, NFR-011):

    manifest.json        format, synthetic flag and label, session start, evening summary, hashes
    scenarios.json       scenarios A, A′, B, B′, C: title, visits, cameras, clip range, clip URLs
    tables/<table>.json  every schema.sql table, rows in a fixed order, JSON columns decoded
    twin.json            3D twin: GLB URL, camera poses and cones, coverage, blind regions
    overlays.json        per camera: SAM boxes and outlines keyed by track (player canvas)
    presets.json         cached results for the live buttons (protect, voice, compile, re-run)
    trace.json           per visit: triage decision, Wonder drafts, verdict inputs, loop log
    eval.json            eval/results.json at export time (or a labelled placeholder)
    bundle.db            a compacted copy of the source SQLite DB
    media/               GLB, stills and clips referenced by URL as /media/<path>
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from vigil.models import (
    CheckIn,
    Config,
    Event,
    ExpectedWindow,
    Gap,
    ModelCall,
    Position,
    Subject,
    ValidationResult,
    Visit,
)
from vigil.store import db

BUNDLE_FORMAT = "vigil-bundle/1"
MANIFEST = "manifest.json"


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dumps(obj), encoding="utf-8", newline="\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_config(config: Config | Path | None) -> Config | None:
    if isinstance(config, Config):
        return config
    if config is None:
        from vigil.settings import get_settings

        config = get_settings().config_path
    if not Path(config).exists():
        return None
    raw = yaml.safe_load(Path(config).read_text(encoding="utf-8"))
    return Config.model_validate(raw)


def default_twin(config: Config | None) -> dict[str, Any]:
    """Twin data when no spatial build exists: cameras and blind regions from the config."""
    if config is None:
        return {"glb_url": None, "cameras": [], "blind_regions": [], "coverage": []}
    return {
        "glb_url": None,
        "cameras": [{"id": c.id, "name": c.name} for c in config.cameras],
        "blind_regions": [r.model_dump() for r in config.blind_regions],
        "coverage": [],
        "site_plan": {"boxes": []},
    }


def _scenarios(
    tables: dict[str, list[dict[str, Any]]], meta: dict[str, Any], media: list[str]
) -> list[dict[str, Any]]:
    titles = meta.get("scenario_titles", {})
    pad = float(meta.get("clip_pad_s", 10.0))
    cameras = [{"id": c["id"], "name": c["name"]} for c in tables["cameras"]]
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for v in tables["visits"]:
        by_scenario.setdefault(v.get("scenario") or "default", []).append(v)
    out = []
    for sid in sorted(by_scenario):
        visits = by_scenario[sid]
        t0 = min(v["t0"] for v in visits) - pad
        t1 = max(v["t1"] for v in visits) + pad
        cams = []
        for cam in cameras:
            clip = next(
                (m for m in media if m.startswith(f"clips/{sid}/{cam['id']}.")),
                None,
            )
            cams.append({**cam, "clip_url": f"/media/{clip}" if clip else None, "clip_t0": t0})
        out.append(
            {
                "id": sid,
                "title": titles.get(sid, f"Scenario {sid}"),
                "visit_ids": [v["id"] for v in visits],
                "verdicts": [v.get("verdict") for v in visits],
                "t0": round(t0, 3),
                "t1": round(t1, 3),
                "cameras": cams,
            }
        )
    return out


def _summary(tables: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {
        "motion_triggers": sum(1 for w in tables["windows"] if w.get("trigger") == "motion"),
        "visits": len(tables["visits"]),
        "alerts": sum(1 for v in tables["visits"] if v.get("verdict") == "needs_attention"),
    }


def export_bundle(
    out: Path,
    db_path: Path | None = None,
    *,
    config: Config | Path | None = None,
    twin: dict[str, Any] | None = None,
    overlays: dict[str, Any] | None = None,
    presets: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
    eval_results: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    media: dict[str, bytes | Path] | None = None,
) -> Path:
    """Write the demo bundle from a processed DB. Returns the bundle directory.

    Extras the DB does not hold (twin geometry, overlays, presets, evaluation) are passed in;
    sensible defaults come from config/cameras.yaml, track overlay files and eval/results.json.
    """
    from vigil.settings import REPO_ROOT, get_settings

    db_path = Path(db_path) if db_path is not None else get_settings().db_path
    if not db_path.exists():
        raise FileNotFoundError(
            f"no database at {db_path}; run `vigil process` first (or pass db_path)"
        )
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    meta = dict(meta or {})

    src = db.connect(db_path)
    try:
        tables = {
            name: [db.decode_row(name, r) for r in db.rows(src, name)]
            for name in sorted(db.ORDER_BY)
            if name in db.table_names(src)
        }
        dest = out / "bundle.db"
        if dest.exists():
            dest.unlink()
        src.execute("VACUUM INTO ?", (str(dest),))
    finally:
        src.close()

    for name, table_rows in tables.items():
        _write_json(out / "tables" / f"{name}.json", table_rows)

    media_names: list[str] = []
    for rel, content in sorted((media or {}).items()):
        target = out / "media" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Path):
            shutil.copyfile(content, target)
        else:
            target.write_bytes(content)
        media_names.append(rel)

    cfg = _load_config(config)
    if overlays is None:
        overlays = {}
        for track in tables.get("tracks", []):
            path = track.get("overlay_path")
            if path and Path(path).exists():
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                overlays.setdefault(track["camera_id"], {})[track["id"]] = data
    if eval_results is None:
        eval_file = REPO_ROOT / "eval" / "results.json"
        eval_results = (
            json.loads(eval_file.read_text(encoding="utf-8"))
            if eval_file.exists()
            else {"status": "not measured", "metrics": []}
        )

    _write_json(out / "twin.json", twin if twin is not None else default_twin(cfg))
    _write_json(out / "overlays.json", overlays)
    _write_json(out / "presets.json", presets or {})
    _write_json(out / "trace.json", trace or {})
    _write_json(out / "eval.json", eval_results)
    _write_json(out / "scenarios.json", _scenarios(tables, meta, media_names))

    written = [f"tables/{name}.json" for name in tables] + [f"media/{m}" for m in media_names]
    written += ["twin.json", "overlays.json", "presets.json", "trace.json", "eval.json"]
    written += ["scenarios.json"]
    files = {rel: _sha256(out / rel) for rel in sorted(written)}
    manifest = {
        "format": BUNDLE_FORMAT,
        "synthetic": bool(meta.get("synthetic", False)),
        "label": meta.get("label", "Recorded evening"),
        "session_start": meta.get("session_start"),
        "timezone": meta.get("timezone", cfg.timezone if cfg else "America/Los_Angeles"),
        "summary": _summary(tables),
        "notes": meta.get("notes", []),
        "files": files,
    }
    _write_json(out / MANIFEST, manifest)
    return out


# ---------------------------------------------------------------------------
# Loader (used by the sandbox API)
# ---------------------------------------------------------------------------


@dataclass
class Bundle:
    root: Path
    manifest: dict[str, Any]
    scenarios: list[dict[str, Any]]
    visits: list[Visit]
    events: list[Event]
    gaps: list[Gap]
    positions: list[Position]
    model_calls: list[ModelCall]
    validations: list[tuple[str, ValidationResult]]
    subjects: list[Subject]
    expected_windows: list[ExpectedWindow]
    checkins: list[CheckIn]
    tables: dict[str, list[dict[str, Any]]]
    twin: dict[str, Any]
    overlays: dict[str, Any]
    presets: dict[str, Any]
    trace: dict[str, Any]
    eval: dict[str, Any]
    _visit_index: dict[str, Visit] = field(default_factory=dict, repr=False)

    @property
    def rule_hits(self) -> list[dict[str, Any]]:
        return self.tables.get("rule_hits", [])

    @property
    def watches(self) -> list[dict[str, Any]]:
        return self.tables.get("watches", [])

    @property
    def rules(self) -> list[dict[str, Any]]:
        return self.tables.get("rules", [])

    @property
    def cameras(self) -> list[dict[str, Any]]:
        return self.tables.get("cameras", [])

    @property
    def protected_objects(self) -> list[dict[str, Any]]:
        return self.tables.get("protected_objects", [])

    def visit(self, visit_id: str) -> Visit | None:
        return self._visit_index.get(visit_id)

    def events_for(self, visit_id: str) -> list[Event]:
        return [e for e in self.events if e.visit_id == visit_id]

    def gaps_for(self, visit_id: str) -> list[Gap]:
        return [g for g in self.gaps if g.visit_id == visit_id]

    def positions_for(self, track_ids: Any) -> list[Position]:
        ids = set(track_ids)
        return [p for p in self.positions if p.track_id in ids]

    def calls_for(self, visit_id: str | None) -> list[ModelCall]:
        if visit_id is None:
            return list(self.model_calls)
        return [c for c in self.model_calls if c.visit_id == visit_id]

    def validations_for(self, visit_id: str) -> list[ValidationResult]:
        return [v for vid, v in self.validations if vid == visit_id]

    def subjects_for(self, visit_id: str) -> list[Subject]:
        """Subject chains of a visit with their roles and role_basis (FR-044)."""
        return [s for s in self.subjects if s.visit_id == visit_id]

    def subject_for_track(self, track_id: str) -> Subject | None:
        return next((s for s in self.subjects if track_id in s.track_ids), None)

    def scenario(self, scenario_id: str) -> dict[str, Any] | None:
        return next((s for s in self.scenarios if s["id"] == scenario_id), None)


def _read(root: Path, rel: str, default: Any) -> Any:
    path = root / rel
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle(root: Path) -> Bundle:
    """Read an exported bundle and validate its rows against the shared contracts."""
    root = Path(root)
    if not (root / MANIFEST).exists():
        raise FileNotFoundError(f"{root} is not a Vigil bundle (no {MANIFEST})")
    manifest = _read(root, MANIFEST, {})
    tables = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((root / "tables").glob("*.json"))
    }
    events = [db.event_from_row(r) for r in tables.get("events", [])]
    gaps = [db.gap_from_row(r) for r in tables.get("gaps", [])]
    visits = []
    for r in tables.get("visits", []):
        v_events = [e for e in events if e.visit_id == r["id"]]
        v_gaps = [g for g in gaps if g.visit_id == r["id"]]
        visits.append(db.visit_from_row(r, v_events, v_gaps))
    positions = [db.position_from_row(r) for r in tables.get("positions", [])]
    positions.sort(key=lambda p: (p.t, p.track_id))
    calls = [db.model_call_from_row(r) for r in tables.get("model_calls", [])]
    validations = [
        (r["visit_id"], db.validation_from_row(r)) for r in tables.get("validations", [])
    ]
    subjects = [db.subject_from_row(r) for r in tables.get("subjects", [])]
    windows = [db.expected_window_from_row(r) for r in tables.get("expected_windows", [])]
    checkins = [db.checkin_from_row(r) for r in tables.get("checkins", [])]
    bundle = Bundle(
        root=root,
        manifest=manifest,
        scenarios=_read(root, "scenarios.json", []),
        visits=visits,
        events=events,
        gaps=gaps,
        positions=positions,
        model_calls=calls,
        validations=validations,
        subjects=subjects,
        expected_windows=windows,
        checkins=checkins,
        tables=tables,
        twin=_read(root, "twin.json", {}),
        overlays=_read(root, "overlays.json", {}),
        presets=_read(root, "presets.json", {}),
        trace=_read(root, "trace.json", {}),
        eval=_read(root, "eval.json", {}),
    )
    bundle._visit_index = {v.id: v for v in visits}
    return bundle


def bundle_db(bundle: Bundle) -> sqlite3.Connection | None:
    """Open the bundle's DB copy read-only, if present."""
    path = bundle.root / "bundle.db"
    if not path.exists():
        return None
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
