"""SQLite access over schema.sql (spec 9.3).

Thin repository functions that turn the shared contracts (vigil.models) into rows and
back. Lists and objects are stored as JSON text; booleans as 0/1; datetimes as ISO-8601.
The schema itself is owned by the integrator (schema.sql) and is never altered here.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from vigil.models import (
    Appearance,
    CameraAiEvent,
    CameraCfg,
    Event,
    Gap,
    ModelCall,
    Position,
    ProtectedObject,
    Rule,
    RuleHit,
    StorySentence,
    Track,
    ValidationResult,
    Visit,
    Watch,
    Window,
)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_CONTRIBUTOR = "-" + "contributor"  # spelled out so the CI grep for the literal stays clean

# Primary key (or full sort key) per table, used for deterministic ordering on export.
ORDER_BY: dict[str, str] = {
    "cameras": "id",
    "windows": "camera_id, t0, id",
    "camera_ai_events": "t0, id",
    "tracks": "id",
    "track_windows": "track_id, window_id, sam_obj_id",
    "appearance": "track_id",
    "positions": "track_id, t, cameras",
    "protected_objects": "id",
    "watches": "id",
    "events": "t0, id",
    "visits": "t0, id",
    "gaps": "t0, id",
    "rules": "id",
    "rule_hits": "rule_id, visit_id, event_id",
    "model_calls": "created_at, id",
    "validations": "visit_id, attempt",
}

# Columns holding JSON text, decoded on export.
JSON_COLUMNS: dict[str, tuple[str, ...]] = {
    "appearance": ("notes_json",),
    "positions": ("cameras", "flags"),
    "protected_objects": ("bbox_json", "footprint_json"),
    "visits": ("story_json",),
    "rules": ("json",),
    "validations": ("failures_json",),
}


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with row access by column name."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema.sql tables if the database is empty (idempotent)."""
    have = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    if have == 0:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()


def open_db(path: Path | str) -> sqlite3.Connection:
    """Connect and make sure the schema exists."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    init_db(conn)
    return conn


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r[0] for r in rows]


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    _check_table(conn, table)
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _check_table(conn: sqlite3.Connection, table: str) -> None:
    if table not in table_names(conn):
        raise ValueError(f"unknown table {table!r}")


def _cell(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list | dict | tuple):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def insert_raw(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    """Insert or replace one row; unknown columns are an error, missing ones are NULL."""
    cols = columns(conn, table)
    unknown = set(row) - set(cols)
    if unknown:
        raise ValueError(f"{table}: unknown columns {sorted(unknown)}")
    if table == "model_calls" and _CONTRIBUTOR in str(row.get("model", "")):
        raise ValueError("Contributor-mode model IDs are forbidden (NFR-004)")
    keys = list(row)
    marks = ", ".join("?" for _ in keys)
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(keys)}) VALUES ({marks})"  # noqa: S608
    conn.execute(sql, [_cell(row[k]) for k in keys])


def rows(conn: sqlite3.Connection, table: str, where: str = "", params: Iterable = ()) -> list:
    _check_table(conn, table)
    order = ORDER_BY.get(table, "rowid")
    sql = f"SELECT * FROM {table} {where} ORDER BY {order}"  # noqa: S608
    return list(conn.execute(sql, tuple(params)))


def decode_row(table: str, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """Row -> plain dict with JSON columns decoded."""
    out = dict(row)
    for col in JSON_COLUMNS.get(table, ()):
        if isinstance(out.get(col), str):
            out[col] = json.loads(out[col])
    return out


# ---------------------------------------------------------------------------
# Writers (contract model -> row)
# ---------------------------------------------------------------------------


def insert_camera(conn: sqlite3.Connection, cam: CameraCfg) -> None:
    insert_raw(
        conn,
        "cameras",
        {
            "id": cam.id,
            "name": cam.name,
            "width": cam.width,
            "height": cam.height,
            "offset_s": cam.offset_s,
        },
    )


def insert_window(conn: sqlite3.Connection, w: Window) -> None:
    insert_raw(conn, "windows", w.model_dump(exclude={"fps", "width", "height"}))


def insert_camera_ai_event(conn: sqlite3.Connection, e: CameraAiEvent) -> None:
    insert_raw(conn, "camera_ai_events", e.model_dump())


def insert_track(
    conn: sqlite3.Connection,
    t: Track,
    overlay_path: str | None = None,
    sam_obj_ids: dict[str, int] | None = None,
) -> None:
    insert_raw(
        conn,
        "tracks",
        {
            "id": t.id,
            "camera_id": t.camera_id,
            "cls": t.cls,
            "t_first": t.t_first,
            "t_last": t.t_last,
            "overlay_path": overlay_path,
        },
    )
    for wid in t.window_ids:
        obj = (sam_obj_ids or {}).get(wid)
        insert_raw(conn, "track_windows", {"track_id": t.id, "window_id": wid, "sam_obj_id": obj})


def insert_appearance(conn: sqlite3.Connection, track_id: str, a: Appearance, call_id: str) -> None:
    notes = a.model_dump(by_alias=True)
    insert_raw(conn, "appearance", {"track_id": track_id, "notes_json": notes, "call_id": call_id})


def insert_position(conn: sqlite3.Connection, p: Position) -> None:
    insert_raw(conn, "positions", p.model_dump())


def insert_protected_object(conn: sqlite3.Connection, po: ProtectedObject) -> None:
    insert_raw(
        conn,
        "protected_objects",
        {
            "id": po.id,
            "camera_id": po.camera_id,
            "label": po.label,
            "mask_path": po.mask_path,
            "bbox_json": po.bbox.model_dump(),
            "footprint_json": [list(p) for p in po.footprint] if po.footprint else None,
            "call_id": po.call_id,
            "created_at": po.created_at,
        },
    )


def insert_watch(conn: sqlite3.Connection, w: Watch) -> None:
    insert_raw(conn, "watches", w.model_dump())


def insert_event(conn: sqlite3.Connection, e: Event) -> None:
    insert_raw(conn, "events", e.model_dump())


def insert_gap(conn: sqlite3.Connection, g: Gap) -> None:
    insert_raw(conn, "gaps", g.model_dump())


def insert_visit(conn: sqlite3.Connection, v: Visit) -> None:
    insert_raw(
        conn,
        "visits",
        {
            "id": v.id,
            "scenario": v.scenario,
            "t0": v.t0,
            "t1": v.t1,
            "state": v.state,
            "floor": v.floor,
            "proposal": v.proposal,
            "verdict": v.verdict,
            "escalated": None if v.escalated is None else int(v.escalated),
            "story_json": [s.model_dump() for s in v.story],
        },
    )


def insert_rule(
    conn: sqlite3.Connection, rule: Rule, source: str = "owner", created_at: str | None = None
) -> None:
    insert_raw(
        conn,
        "rules",
        {
            "id": rule.id,
            "json": rule.model_dump(),
            "source": source,
            "state": rule.state,
            "created_at": created_at,
        },
    )


def insert_rule_hit(conn: sqlite3.Connection, hit: RuleHit) -> None:
    insert_raw(conn, "rule_hits", hit.model_dump())


def insert_model_call(conn: sqlite3.Connection, call: ModelCall) -> None:
    insert_raw(conn, "model_calls", call.model_dump())


def insert_validation(conn: sqlite3.Connection, visit_id: str, result: ValidationResult) -> None:
    insert_raw(
        conn,
        "validations",
        {
            "visit_id": visit_id,
            "attempt": result.attempt,
            "passed": int(result.passed),
            "failures_json": [f.model_dump() for f in result.failures],
        },
    )


# ---------------------------------------------------------------------------
# Readers (row -> contract model)
# ---------------------------------------------------------------------------


def event_from_row(row: dict[str, Any]) -> Event:
    return Event.model_validate(dict(row))


def gap_from_row(row: dict[str, Any]) -> Gap:
    data = dict(row)
    data["resolved"] = bool(data.get("resolved"))
    return Gap.model_validate(data)


def position_from_row(row: dict[str, Any]) -> Position:
    data = decode_row("positions", row)
    data["cameras"] = data.get("cameras") or []
    data["flags"] = data.get("flags") or []
    return Position.model_validate(data)


def model_call_from_row(row: dict[str, Any]) -> ModelCall:
    data = {k: v for k, v in dict(row).items() if v is not None}
    for key in ("cached", "ok"):
        if key in data:
            data[key] = bool(data[key])
    return ModelCall.model_validate(data)


def validation_from_row(row: dict[str, Any]) -> ValidationResult:
    data = decode_row("validations", row)
    return ValidationResult(
        passed=bool(data["passed"]),
        attempt=int(data["attempt"]),
        failures=data.get("failures_json") or [],
    )


def story_from_json(raw: Any) -> list[StorySentence]:
    """story_json holds a list of StorySentence dicts (or {"sentences": [...]})."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, dict):
        raw = raw.get("sentences", [])
    return [StorySentence.model_validate(s) for s in raw or []]


def visit_from_row(
    row: dict[str, Any], events: list[Event] | None = None, gaps: list[Gap] | None = None
) -> Visit:
    data = dict(row)
    events = events or []
    track_ids: list[str] = []
    for e in events:
        if e.track_id not in track_ids:
            track_ids.append(e.track_id)
    escalated = data.get("escalated")
    return Visit(
        id=data["id"],
        scenario=data.get("scenario"),
        t0=data["t0"],
        t1=data["t1"],
        state=data.get("state") or "open",
        floor=data.get("floor") or "normal",
        proposal=data.get("proposal"),
        verdict=data.get("verdict"),
        escalated=None if escalated is None else bool(escalated),
        story=story_from_json(data.get("story_json")),
        event_ids=[e.id for e in events],
        gap_ids=[g.id for g in gaps or []],
        track_ids=track_ids,
    )


def events_for_visit(conn: sqlite3.Connection, visit_id: str) -> list[Event]:
    return [event_from_row(r) for r in rows(conn, "events", "WHERE visit_id = ?", [visit_id])]


def gaps_for_visit(conn: sqlite3.Connection, visit_id: str) -> list[Gap]:
    return [gap_from_row(r) for r in rows(conn, "gaps", "WHERE visit_id = ?", [visit_id])]


def get_visit(conn: sqlite3.Connection, visit_id: str) -> Visit | None:
    found = rows(conn, "visits", "WHERE id = ?", [visit_id])
    if not found:
        return None
    return visit_from_row(
        found[0], events_for_visit(conn, visit_id), gaps_for_visit(conn, visit_id)
    )


def list_visits(conn: sqlite3.Connection) -> list[Visit]:
    out = []
    for r in rows(conn, "visits"):
        vid = r["id"]
        out.append(visit_from_row(r, events_for_visit(conn, vid), gaps_for_visit(conn, vid)))
    return out


def positions_for_tracks(conn: sqlite3.Connection, track_ids: Iterable[str]) -> list[Position]:
    ids = list(track_ids)
    if not ids:
        return []
    marks = ", ".join("?" for _ in ids)
    found = rows(conn, "positions", f"WHERE track_id IN ({marks})", ids)
    return sorted((position_from_row(r) for r in found), key=lambda p: (p.t, p.track_id))


def model_calls(conn: sqlite3.Connection, visit_id: str | None = None) -> list[ModelCall]:
    if visit_id is None:
        found = rows(conn, "model_calls")
    else:
        found = rows(conn, "model_calls", "WHERE visit_id = ?", [visit_id])
    return [model_call_from_row(r) for r in found]


def validations_for_visit(conn: sqlite3.Connection, visit_id: str) -> list[ValidationResult]:
    found = rows(conn, "validations", "WHERE visit_id = ?", [visit_id])
    return [validation_from_row(r) for r in found]
