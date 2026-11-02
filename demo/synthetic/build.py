"""Build the SYNTHETIC demo bundle for scenarios A, B and C (FR-027, spec section 4).

Everything here is invented: no footage, no real house, no people, no location. The geometry
is a measured-site-plan stand-in (spec 7, fallback ladder level 3) laid out to match the
sample config/cameras.yaml, and the camera views in the sandbox are drawn on canvases from
this data. It exists so the sandbox, the API and the E2E tests work before the recorded
evening is exported by `vigil export`.

Run from the repo root:  uv run python demo/synthetic/build.py
Re-running gives byte-identical JSON and GLB files (tested in tests/integration/test_store.py).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import struct
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.ops import unary_union

from vigil.models import (
    ActiveWindow,
    Appearance,
    Box,
    Config,
    Event,
    Gap,
    ModelCall,
    Position,
    ProtectedObject,
    Rule,
    RuleHit,
    RuleTarget,
    StorySentence,
    Track,
    ValidationFailure,
    ValidationResult,
    Visit,
    Watch,
    Window,
)
from vigil.store import db
from vigil.store.export import export_bundle

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
SESSION_START = datetime.fromisoformat("2026-10-30T18:00:00-07:00")
W, H = 1280, 720
LABEL = "SYNTHETIC DEMO DATA: invented scenes drawn from JSON, no real footage or home"

SAM = "sam-3.1"
SPARK = "muse-spark-1.3"
WONDER = "muse-wonder-1.0"

# ---------------------------------------------------------------------------
# Site plan (world metres: x along the front wall, y up, z towards the backyard)
# ---------------------------------------------------------------------------

BOXES: list[dict[str, Any]] = [
    {"id": "house", "name": "House", "kind": "building", "min": [-6.0, 0.0], "max": [3.5, 7.0],
     "h": 3.0},
    {"id": "shed", "name": "Shed", "kind": "building", "min": [4.1, 7.6], "max": [7.3, 9.0],
     "h": 2.2},
    {"id": "fence_left", "name": "Left fence", "kind": "fence", "min": [9.4, -1.0],
     "max": [9.6, 14.0], "h": 1.8},
    {"id": "fence_back", "name": "Back fence", "kind": "fence", "min": [-9.6, 13.9],
     "max": [9.6, 14.1], "h": 1.8},
    {"id": "fence_right", "name": "Right fence", "kind": "fence", "min": [-9.6, -1.0],
     "max": [-9.4, 14.0], "h": 1.8},
    {"id": "gate_fence_a", "name": "Side fence", "kind": "fence", "min": [3.5, 2.95],
     "max": [5.5, 3.05], "h": 1.6},
    {"id": "gate_fence_b", "name": "Side fence", "kind": "fence", "min": [6.7, 2.95],
     "max": [9.4, 3.05], "h": 1.6},
    {"id": "side_gate", "name": "Side gate", "kind": "protected", "min": [5.5, 2.95],
     "max": [6.7, 3.05], "h": 1.5},
    {"id": "bin", "name": "Recycling bin", "kind": "object", "min": [-8.4, 4.3],
     "max": [-7.8, 4.9], "h": 1.1},
]  # fmt: skip
GROUND = {"min": [-12.0, -12.0], "max": [12.0, 16.0]}

CAMERA_POSES: dict[str, dict[str, Any]] = {
    "front": {"position": [0.8, 2.6, -0.3], "look_at": [1.2, 0.0, -7.0], "hfov_deg": 100.0,
              "range_m": 11.0},
    "side_left": {"position": [3.7, 2.6, 0.2], "look_at": [6.4, 0.0, 7.5], "hfov_deg": 85.0,
                  "range_m": 11.0},
    "side_right": {"position": [-6.2, 2.6, 0.2], "look_at": [-7.6, 0.0, 7.0], "hfov_deg": 80.0,
                   "range_m": 10.0},
    "backyard": {"position": [-5.8, 2.7, 7.3], "look_at": [-1.0, 0.0, 12.5], "hfov_deg": 90.0,
                 "range_m": 10.0},
}  # fmt: skip

CALIBRATION = {  # synthetic figures shown in "How this was decided" (spec 4, step 4)
    "front": {"reproj_mean_px": 2.1, "heldout_ground_m": 0.14, "method": "pnp_ransac"},
    "side_left": {"reproj_mean_px": 2.6, "heldout_ground_m": 0.18, "method": "pnp_ransac"},
    "side_right": {"reproj_mean_px": 3.1, "heldout_ground_m": 0.21, "method": "pnp_ransac"},
    "backyard": {"reproj_mean_px": 2.4, "heldout_ground_m": 0.16, "method": "homography"},
}


def r3(v: float) -> float:
    return round(float(v), 3)


def noise(key: str) -> float:
    """Deterministic value in [0, 1) from a key (no global RNG state)."""
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0x100000000


def clock(t: float) -> str:
    return (SESSION_START + timedelta(seconds=t)).strftime("%I:%M %p").lstrip("0")


def iso(t: float) -> datetime:
    return SESSION_START + timedelta(seconds=round(t))


# ---------------------------------------------------------------------------
# Synthetic pinhole camera (same model as web/player.js draws)
# ---------------------------------------------------------------------------


class PinholeCam:
    def __init__(self, pose: dict[str, Any]) -> None:
        self.pos = np.array(pose["position"], dtype=float)
        look = np.array(pose["look_at"], dtype=float)
        f = look - self.pos
        self.f = f / np.linalg.norm(f)
        r = np.cross(self.f, [0.0, 1.0, 0.0])
        self.r = r / np.linalg.norm(r)
        self.u = np.cross(self.r, self.f)
        self.fx = (W / 2) / math.tan(math.radians(pose["hfov_deg"]) / 2)

    def project(self, p: Any) -> tuple[float, float] | None:
        d = np.asarray(p, dtype=float) - self.pos
        zc = float(d @ self.f)
        if zc <= 0.2:
            return None
        return (W / 2 + self.fx * float(d @ self.r) / zc, H / 2 - self.fx * float(d @ self.u) / zc)

    def depth(self, p: Any) -> float:
        return float((np.asarray(p, dtype=float) - self.pos) @ self.f)


def _hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _clampbox(xs: list[float], ys: list[float]) -> list[float] | None:
    x1, x2 = max(0.0, min(xs)), min(float(W), max(xs))
    y1, y2 = max(0.0, min(ys)), min(float(H), max(ys))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    return [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)]


def project_person(cam: PinholeCam, x: float, z: float) -> dict[str, Any] | None:
    foot = cam.project([x, 0.0, z])
    head = cam.project([x, 1.7, z])
    if foot is None or head is None:
        return None
    half = cam.fx * 0.25 / max(cam.depth([x, 0.85, z]), 0.2)
    box = _clampbox([foot[0] - half, foot[0] + half], [head[1], foot[1]])
    if box is None:
        return None
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    rx, ry = (box[2] - box[0]) / 2, (box[3] - box[1]) / 2
    outline = [
        [round(cx + rx * math.cos(a) * (0.55 if a < math.pi else 1.0), 1),
         round(cy + ry * math.sin(a), 1)]
        for a in (2 * math.pi * k / 12 for k in range(12))
    ]  # fmt: skip
    return {"box": box, "outline": outline}


def project_block(
    cam: PinholeCam, x0: float, z0: float, x1: float, z1: float, h: float
) -> dict[str, Any] | None:
    corners = [[x, y, z] for x in (x0, x1) for y in (0.0, h) for z in (z0, z1)]
    pts = [cam.project(c) for c in corners]
    if any(p is None for p in pts):
        return None
    pts2 = [(round(p[0], 1), round(p[1], 1)) for p in pts if p is not None]
    box = _clampbox([p[0] for p in pts2], [p[1] for p in pts2])
    if box is None:
        return None
    return {"box": box, "outline": [list(p) for p in _hull(pts2)]}


# ---------------------------------------------------------------------------
# Paths (t, x, z) per track; positions at 2 Hz; never inside a gap
# ---------------------------------------------------------------------------


def path_at(waypoints: list[tuple[float, float, float]], t: float) -> tuple[float, float]:
    if t <= waypoints[0][0]:
        return waypoints[0][1], waypoints[0][2]
    for (ta, xa, za), (tb, xb, zb) in itertools.pairwise(waypoints):
        if ta <= t <= tb:
            k = 0.0 if tb == ta else (t - ta) / (tb - ta)
            return xa + (xb - xa) * k, za + (zb - za) * k
    return waypoints[-1][1], waypoints[-1][2]


TRACKS: dict[str, dict[str, Any]] = {
    # Scenario A: routine departure, front camera
    "t_a1": {"camera": "front", "cls": "person", "tag": "T1", "visit": "v_a",
             "path": [(2522, 0.0, -0.4), (2531, 2.6, -2.8), (2546, 4.3, -4.4)]},
    "t_a2": {"camera": "front", "cls": "car", "tag": "T2", "visit": "v_a",
             "path": [(2540, 5.2, -5.0), (2552, 5.2, -5.0), (2578, 5.4, -10.5)]},
    # Scenario B: delivery, front camera; the package stays
    "t_b1": {"camera": "front", "cls": "person", "tag": "T1", "visit": "v_b",
             "path": [(5462, 2.2, -8.0), (5478, 0.7, -1.3), (5496, 0.8, -1.2),
                      (5520, 2.6, -8.4)]},
    "t_b2": {"camera": "front", "cls": "package", "tag": "T2", "visit": "v_b",
             "path": [(5494, 0.4, -0.9), (5530, 0.4, -0.9)]},
    # Scenario C: night visit with the shed gap g4
    "t_c0": {"camera": "front", "cls": "person", "tag": "T1", "visit": "v_c",
             "path": [(15170, 3.0, -4.5), (15190, 4.0, -0.6)]},
    "t_c1": {"camera": "side_left", "cls": "person", "tag": "T1", "visit": "v_c",
             "path": [(15186, 3.9, -0.8), (15230, 5.6, 2.2), (15245, 6.1, 2.75),
                      (15249, 6.1, 2.8), (15256, 6.0, 5.0), (15263, 6.6, 7.3)]},
    "t_c2": {"camera": "side_left", "cls": "person", "tag": "T1", "visit": "v_c",
             "path": [(15304, 7.6, 7.4), (15318, 6.1, 3.0), (15340, 5.0, 1.0),
                      (15360, 4.0, -0.6)]},
    "t_c3": {"camera": "front", "cls": "person", "tag": "T1", "visit": "v_c",
             "path": [(15356, 3.9, -0.8), (15385, 2.5, -5.0)]},
}  # fmt: skip

# (from_track, to_track, t0, t1): both cameras see the subject; positions are fused.
FUSED = [("t_c0", "t_c1", 15186.0, 15190.0), ("t_c2", "t_c3", 15356.0, 15360.0)]
LOW_CONFIDENCE = ("t_c1", 15257.0, 15263.0)  # feet hidden behind the bins near the shed


def positions_for(track_id: str) -> list[Position]:
    spec = TRACKS[track_id]
    cam = CAMERA_POSES[spec["camera"]]["position"]
    t0, t1 = spec["path"][0][0], spec["path"][-1][0]
    out: list[Position] = []
    t = float(t0)
    while t <= t1 + 1e-9:
        x, z = path_at(spec["path"], t)
        method, cams, flags = "footpoint", [spec["camera"]], []
        dist = math.hypot(x - cam[0], z - cam[2])
        r95 = 0.2 + 0.035 * dist
        skip = False
        for a, b, f0, f1 in FUSED:
            if f0 <= t <= f1:
                if track_id == b:
                    skip = True  # one fused estimate per instant, stored on the first track
                elif track_id == a:
                    method, cams, r95 = (
                        "fused",
                        sorted([TRACKS[a]["camera"], TRACKS[b]["camera"]]),
                        0.22,
                    )
        lc_track, lc0, lc1 = LOW_CONFIDENCE
        if track_id == lc_track and lc0 <= t <= lc1:
            method, flags, r95 = "height_prior", ["low_confidence"], 0.9
        if not skip:
            jitter = (noise(f"{track_id}:{t}") - 0.5) * 0.06
            out.append(
                Position(track_id=track_id, t=r3(t), x=r3(x + jitter), y=0.0, z=r3(z - jitter),
                         r95=r3(r95), method=method, cameras=cams, flags=flags)
            )  # fmt: skip
        t += 0.5
    return out


def overlays_for(track_id: str) -> dict[str, Any]:
    spec = TRACKS[track_id]
    cam = PinholeCam(CAMERA_POSES[spec["camera"]])
    frames = []
    t0, t1 = spec["path"][0][0], spec["path"][-1][0]
    t = float(t0)
    while t <= t1 + 1e-9:
        x, z = path_at(spec["path"], t)
        if spec["cls"] == "person":
            shape = project_person(cam, x, z)
        elif spec["cls"] == "car":
            shape = project_block(cam, x - 0.9, z - 2.2, x + 0.9, z + 2.2, 1.5)
        else:
            shape = project_block(cam, x - 0.2, z - 0.15, x + 0.2, z + 0.15, 0.3)
        if shape is not None:
            frames.append({"t": r3(t), **shape})
        t += 1.0
    return {"tag": spec["tag"], "cls": spec["cls"], "visit_id": spec["visit"], "frames": frames}


# ---------------------------------------------------------------------------
# Events, gaps, visits, stories
# ---------------------------------------------------------------------------


def ev(eid, visit, cam, track, typ, t0, t1, target=None) -> Event:
    return Event(id=eid, visit_id=visit, camera_id=cam, track_id=track, type=typ, t0=t0, t1=t1,
                 target=target, clip_t0=t0 - 5.0, clip_t1=t1 + 5.0)  # fmt: skip


EVENTS = [
    ev("e1", "v_a", "front", "t_a1", "enter", 2522, 2523),
    ev("e2", "v_a", "front", "t_a1", "enter", 2531, 2532, "driveway"),
    ev("e3", "v_a", "front", "t_a1", "exit", 2545, 2546),
    ev("e4", "v_a", "front", "t_a2", "exit", 2552, 2578, "driveway"),
    ev("e5", "v_b", "front", "t_b1", "enter", 5462, 5463),
    ev("e6", "v_b", "front", "t_b1", "enter", 5470, 5471, "porch"),
    ev("e7", "v_b", "front", "t_b1", "dwell", 5478, 5496, "porch"),
    ev("e8", "v_b", "front", "t_b1", "exit", 5519, 5520),
    ev("e9", "v_b", "front", "t_b2", "enter", 5494, 5495, "porch"),
    ev("e15", "v_c", "front", "t_c0", "enter", 15170, 15171),
    ev("e16", "v_c", "side_left", "t_c1", "enter", 15186, 15187, "side_yard"),
    ev("e17", "v_c", "side_left", "t_c1", "touch", 15245, 15249, "po_side_gate"),
    ev("e18", "v_c", "side_left", "t_c1", "exit", 15262, 15263, "to_shed_back"),
    ev("e19", "v_c", "side_left", "t_c2", "enter", 15304, 15305, "side_yard"),
    ev("e20", "v_c", "side_left", "t_c2", "cross", 15317, 15319, "side_gate"),
    ev("e21", "v_c", "side_left", "t_c2", "exit", 15359, 15360),
    ev("e22", "v_c", "front", "t_c3", "enter", 15356, 15357),
    ev("e23", "v_c", "front", "t_c3", "exit", 15384, 15385),
]

GAPS = [
    Gap(id="g4", visit_id="v_c", kind="blind_spot", t0=15263.0, t1=15304.0,
        from_camera="side_left", to_camera="side_left", region_id="shed_back", resolved=True),
]  # fmt: skip


def s(text: str, ids: list[str], source: str = "wonder", gap_id: str | None = None):
    return StorySentence(text=text, event_ids=ids, source=source, gap_id=gap_id)


GAP_SENTENCE = s(
    "Not observed for 41 s: they left the Left side view toward the area behind the shed, "
    "which no camera covers. Vigil can't confirm what happened there.",
    ["e18", "e19"],
    "code",
    "g4",
)

STORY_A = [
    s(f"A person was seen on the Front entrance camera at {clock(2522)}.", ["e1", "e3"],
      "template"),
    s(f"A car left the driveway at {clock(2552)}.", ["e4"], "template"),
]  # fmt: skip
STORY_B = [
    s(f"A person walked up to the porch on the Front entrance camera at {clock(5462)}.",
      ["e5", "e6"]),
    s(f"They stayed on the porch for about 18 s, and a package appeared there at "
      f"{clock(5494)}.", ["e7", "e9"]),
    s(f"They left at {clock(5520)}; the package stayed on the porch.", ["e8", "e9"]),
]  # fmt: skip
STORY_C = [
    s(f"A person walked from the front of the house into the left side yard at "
      f"{clock(15186)}.", ["e15", "e16"]),
    s(f"They touched the side gate at {clock(15245)}.", ["e17"]),
    GAP_SENTENCE,
    s(f"They came back into view on the Left side camera at {clock(15304)} and walked back "
      f"through the side gate.", ["e19", "e20"]),
    s(f"They left past the Front entrance camera at {clock(15385)}.", ["e22", "e23"]),
]  # fmt: skip
REJECTED_C = [
    {"text": STORY_C[0].text, "event_ids": ["e15", "e16"]},
    {"text": STORY_C[1].text, "event_ids": ["e17"]},
    {"text": "He checked the shed door.", "event_ids": []},
    {"text": STORY_C[3].text, "event_ids": ["e19", "e20"]},
]
REJECTION_C = [
    ValidationFailure(check="uncited", sentence_index=2,
                      detail="'He checked the shed door.' cites no event"),
    ValidationFailure(check="banned_word", sentence_index=2,
                      detail="'He' assumes gender; the subject is always 'a person' or 'they'"),
]  # fmt: skip

VISITS = [
    Visit(id="v_a", scenario="A", t0=2522, t1=2578, state="published", floor="normal",
          proposal=None, verdict="normal", escalated=False, story=STORY_A),
    Visit(id="v_b", scenario="B", t0=5462, t1=5530, state="published", floor="normal",
          proposal="noteworthy", verdict="noteworthy", escalated=True, story=STORY_B),
    Visit(id="v_c", scenario="C", t0=15170, t1=15385, state="published",
          floor="needs_attention", proposal="normal", verdict="needs_attention",
          escalated=True, story=STORY_C),
]  # fmt: skip

TITLES = {
    "A": "A · Routine departure",
    "B": "B · Delivery on the porch",
    "C": "C · Night visit to the side gate",
}


# ---------------------------------------------------------------------------
# Windows and the model-call ledger
# ---------------------------------------------------------------------------


class Ledger:
    def __init__(self) -> None:
        self.calls: list[ModelCall] = []

    def add(self, model: str, purpose: str, visit_id: str | None, key: str, t: float,
            **kw: Any) -> str:  # fmt: skip
        cid = f"call_{len(self.calls) + 1:04d}"
        req = hashlib.sha256(f"{model}|{purpose}|{key}".encode()).hexdigest()[:16]
        call = ModelCall(id=cid, model=model, purpose=purpose, visit_id=visit_id, req_hash=req,
                         cached=True, ok=True, created_at=iso(t), **kw)  # fmt: skip
        self.calls.append(call)
        return cid


def sam_cost(frames: int) -> float:
    return round(max(frames, 50) * 0.20 / 1000, 6)


def tok_cost(model: str, tin: int, tout: int) -> float:
    pin, pout = (1.25, 4.25) if model == SPARK else (4.0, 20.0)
    return round(tin * pin / 1e6 + tout * pout / 1e6, 6)


def build_windows_and_calls(ledger: Ledger) -> list[Window]:
    windows: list[Window] = []
    for visit in VISITS:
        by_cam: dict[str, list[Event]] = {}
        for e in EVENTS:
            if e.visit_id == visit.id:
                by_cam.setdefault(e.camera_id, []).append(e)
        for cam, evs in sorted(by_cam.items()):
            start = min(e.t0 for e in evs) - 4
            end = max(e.t1 for e in evs) + 2
            t = float(start)
            while t < end:
                wid = f"w_{cam}_{int(t)}"
                windows.append(Window(id=wid, camera_id=cam, t0=t, t1=t + 10, motion=r3(
                    0.08 + 0.1 * noise(wid)), trigger="motion", status="processed",
                    path=f"windows/{wid}.mp4"))  # fmt: skip
                phrases = ["person", "car"] if cam == "front" else ["person"]
                if visit.id == "v_b" and t >= 5496:
                    phrases.append("package")  # the watch added by the closed loop (FR-020)
                for phrase in phrases:
                    ledger.add(SAM, "track", visit.id, f"{wid}|{phrase}", t + 14,
                               latency_ms=int(2600 + 2400 * noise(wid + phrase)), units=100,
                               cost_usd=sam_cost(100))  # fmt: skip
                t += 8.0
    # Motion triggers that never became visits: wind in trees, headlights, a moth.
    for k in range(19):
        cam = ["front", "side_left", "side_right", "backyard"][k % 4]
        t = 900.0 + k * 821.0
        wid = f"w_{cam}_{int(t)}"
        windows.append(Window(id=wid, camera_id=cam, t0=t, t1=t + 10, motion=r3(
            0.02 + 0.03 * noise(wid)), trigger="motion", status="idle",
            path=f"windows/{wid}.mp4"))  # fmt: skip
    return windows


def build_calls(ledger: Ledger) -> dict[str, Any]:
    """Appearance, triage and story calls; returns per-visit trace facts."""
    trace: dict[str, Any] = {}
    for tid, spec in TRACKS.items():
        if spec["cls"] in ("person", "car"):
            t_end = spec["path"][-1][0]
            ledger.add(SPARK, "appearance", spec["visit"], tid, t_end + 20,
                       latency_ms=int(5200 + 3000 * noise(tid)), in_tokens=30000,
                       out_tokens=220, cost_usd=tok_cost(SPARK, 30000, 220))  # fmt: skip
    tri_a = ledger.add(SPARK, "triage", "v_a", "v_a", 2600, latency_ms=1310, in_tokens=820,
                       out_tokens=60, cost_usd=tok_cost(SPARK, 820, 60))  # fmt: skip
    tri_b = ledger.add(SPARK, "triage", "v_b", "v_b", 5560, latency_ms=1420, in_tokens=870,
                       out_tokens=64, cost_usd=tok_cost(SPARK, 870, 64))  # fmt: skip
    story_b = ledger.add(WONDER, "story", "v_b", "v_b|1", 5575, latency_ms=17800,
                         in_tokens=5900, out_tokens=780,
                         cost_usd=tok_cost(WONDER, 5900, 780))  # fmt: skip
    draft_c1 = ledger.add(WONDER, "story", "v_c", "v_c|1", 15420, latency_ms=19400,
                          in_tokens=6400, out_tokens=820,
                          cost_usd=tok_cost(WONDER, 6400, 820))  # fmt: skip
    draft_c2 = ledger.add(WONDER, "story", "v_c", "v_c|2", 15445, latency_ms=18100,
                          in_tokens=6900, out_tokens=760,
                          cost_usd=tok_cost(WONDER, 6900, 760))  # fmt: skip
    trace["v_a"] = {
        "triage": {"escalate": False, "forced": False, "source": "spark", "call_id": tri_a,
                   "reason": "One household departure by car; no rule, object or gap involved."},
        "drafts": [],
        "story_call_id": None,
        "verdict_inputs": {"floor": "normal", "unresolved_gap": False, "proposal": None,
                           "proposal_cited": False, "result": "normal"},
        "watch_proposals": [],
    }  # fmt: skip
    trace["v_b"] = {
        "triage": {"escalate": True, "forced": False, "source": "spark", "call_id": tri_b,
                   "reason": "A new object was left on the porch."},
        "drafts": [{"attempt": 1, "call_id": story_b, "passed": True,
                    "sentences": [x.model_dump() for x in STORY_B]}],
        "story_call_id": story_b,
        "verdict_inputs": {"floor": "normal", "unresolved_gap": False,
                           "proposal": "noteworthy", "proposal_cited": True,
                           "result": "noteworthy"},
        "watch_proposals": [{"camera_id": "front", "phrase": "package",
                             "reason_event_id": "e9", "accepted": True, "watch_id": "w2",
                             "reason": "camera exists; 'package' is on the allowlist; "
                                       "1 of 4 watches on Front entrance"}],
    }  # fmt: skip
    trace["v_c"] = {
        "triage": {"escalate": True, "forced": True, "source": "code", "call_id": None,
                   "reason": "Rule r7 fired and a protected object was touched."},
        "drafts": [
            {"attempt": 1, "call_id": draft_c1, "passed": False, "sentences": REJECTED_C,
             "failures": [f.model_dump() for f in REJECTION_C]},
            {"attempt": 2, "call_id": draft_c2, "passed": True,
             "sentences": [x.model_dump() for x in STORY_C if x.source == "wonder"]},
        ],
        "story_call_id": draft_c2,
        "gap_sentences": ["g4"],
        "verdict_inputs": {"floor": "needs_attention", "unresolved_gap": False,
                           "proposal": "normal", "proposal_cited": True,
                           "result": "needs_attention"},
        "watch_proposals": [],
    }  # fmt: skip
    return trace


# ---------------------------------------------------------------------------
# Twin geometry and the tiny GLB
# ---------------------------------------------------------------------------


def coverage_polygons(config: Config) -> list[dict[str, Any]]:
    blocked = unary_union(
        [ShapelyPolygon(r.polygon_m) for r in config.blind_regions]
        + [ShapelyPolygon([(b["min"][0], b["min"][1]), (b["max"][0], b["min"][1]),
                           (b["max"][0], b["max"][1]), (b["min"][0], b["max"][1])])
           for b in BOXES if b["kind"] == "building"]
    )  # fmt: skip
    out = []
    for cam_id, pose in CAMERA_POSES.items():
        px, _, pz = pose["position"]
        lx, _, lz = pose["look_at"]
        yaw = math.atan2(lx - px, lz - pz)
        half = math.radians(pose["hfov_deg"]) / 2
        pts = [(px, pz)]
        for k in range(13):
            a = yaw - half + 2 * half * k / 12
            pts.append((px + pose["range_m"] * math.sin(a), pz + pose["range_m"] * math.cos(a)))
        fan = ShapelyPolygon(pts).buffer(0).difference(blocked)
        geoms = getattr(fan, "geoms", [fan])
        biggest = max(geoms, key=lambda g: g.area)
        ring = [[round(x, 2), round(z, 2)] for x, z in list(biggest.exterior.coords)[:-1]]
        out.append({"camera_id": cam_id, "polygon_m": ring, "synthetic": True})
    return out


def build_twin(config: Config, protected: list[ProtectedObject]) -> dict[str, Any]:
    cams = []
    for cam in config.cameras:
        pose = CAMERA_POSES[cam.id]
        fx = (W / 2) / math.tan(math.radians(pose["hfov_deg"]) / 2)
        cams.append({
            "id": cam.id,
            "name": cam.name,
            **pose,
            "vfov_deg": round(math.degrees(2 * math.atan((H / 2) / fx)), 2),
            "width": W,
            "height": H,
            "calibration": {**CALIBRATION[cam.id], "synthetic": True},
        })  # fmt: skip
    return {
        "synthetic": True,
        "glb_url": "/media/ground.glb",
        "frame": "x along the front wall, y up, z towards the backyard (metres)",
        "fallback_level": 3,
        "fallback_note": "Synthetic site plan (house, shed and fences as boxes); no LiDAR scan.",
        "ground": GROUND,
        "site_plan": {"boxes": BOXES},
        "cameras": cams,
        "coverage": coverage_polygons(config),
        "blind_regions": [r.model_dump() for r in config.blind_regions],
        "protected_objects": [
            {"id": p.id, "label": p.label, "camera_id": p.camera_id,
             "footprint": [list(q) for q in p.footprint or []]}
            for p in protected
        ],
    }  # fmt: skip


def build_glb() -> bytes:
    """A tiny glTF 2.0 binary: one ground quad and one unit box per material (no textures)."""
    # Unit box: x and z in [-0.5, 0.5], y in [0, 1]; flat normals (24 vertices).
    faces = [
        ((1, 0, 0), [(0.5, 0, -0.5), (0.5, 1, -0.5), (0.5, 1, 0.5), (0.5, 0, 0.5)]),
        ((-1, 0, 0), [(-0.5, 0, 0.5), (-0.5, 1, 0.5), (-0.5, 1, -0.5), (-0.5, 0, -0.5)]),
        ((0, 1, 0), [(-0.5, 1, -0.5), (-0.5, 1, 0.5), (0.5, 1, 0.5), (0.5, 1, -0.5)]),
        ((0, -1, 0), [(-0.5, 0, 0.5), (-0.5, 0, -0.5), (0.5, 0, -0.5), (0.5, 0, 0.5)]),
        ((0, 0, 1), [(0.5, 0, 0.5), (0.5, 1, 0.5), (-0.5, 1, 0.5), (-0.5, 0, 0.5)]),
        ((0, 0, -1), [(-0.5, 0, -0.5), (-0.5, 1, -0.5), (0.5, 1, -0.5), (0.5, 0, -0.5)]),
    ]
    pos, nor, idx = [], [], []
    for n, quad in faces:
        base = len(pos)
        pos.extend(quad)
        nor.extend([n] * 4)
        idx.extend([base, base + 1, base + 2, base, base + 2, base + 3])
    gx0, gz0 = GROUND["min"]
    gx1, gz1 = GROUND["max"]
    gpos = [(gx0, 0, gz0), (gx0, 0, gz1), (gx1, 0, gz1), (gx1, 0, gz0)]
    gnor = [(0, 1, 0)] * 4
    gidx = [0, 1, 2, 0, 2, 3]

    def f32(vs):
        return b"".join(struct.pack("<3f", *v) for v in vs)

    def u16(vs):
        return struct.pack(f"<{len(vs)}H", *vs)

    chunks = [f32(pos), f32(nor), u16(idx), f32(gpos), f32(gnor), u16(gidx)]
    views, offset, binary = [], 0, b""
    for k, c in enumerate(chunks):
        c = c + b"\x00" * (-len(c) % 4)
        target = 34963 if k in (2, 5) else 34962
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(c), "target": target})
        binary += c
        offset += len(c)
    for k, c in enumerate(chunks):
        views[k]["byteLength"] = len(c)

    def acc(view, count, typ, comp, vmin=None, vmax=None):
        a = {"bufferView": view, "componentType": comp, "count": count, "type": typ}
        if vmin is not None:
            a["min"], a["max"] = vmin, vmax
        return a

    accessors = [
        acc(0, 24, "VEC3", 5126, [-0.5, 0, -0.5], [0.5, 1, 0.5]),
        acc(1, 24, "VEC3", 5126),
        acc(2, 36, "SCALAR", 5123),
        acc(3, 4, "VEC3", 5126, [gx0, 0, gz0], [gx1, 0, gz1]),
        acc(4, 4, "VEC3", 5126),
        acc(5, 6, "SCALAR", 5123),
    ]
    colours = {
        "ground": [0.30, 0.38, 0.28, 1], "building": [0.72, 0.70, 0.66, 1],
        "fence": [0.52, 0.44, 0.34, 1], "protected": [0.86, 0.58, 0.22, 1],
        "object": [0.25, 0.45, 0.70, 1],
    }  # fmt: skip
    kinds = list(colours)
    materials = [
        {"name": k, "pbrMetallicRoughness": {"baseColorFactor": colours[k], "metallicFactor": 0,
                                             "roughnessFactor": 1}}
        for k in kinds
    ]  # fmt: skip
    meshes = [
        {
            "name": "ground",
            "primitives": [
                {"attributes": {"POSITION": 3, "NORMAL": 4}, "indices": 5, "material": 0}
            ],
        }
    ]
    for k in kinds[1:]:
        meshes.append({"name": f"box_{k}", "primitives": [
            {"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2,
             "material": kinds.index(k)}]})  # fmt: skip
    nodes = [{"name": "ground", "mesh": 0}]
    for b in BOXES:
        (x0, z0), (x1, z1) = b["min"], b["max"]
        nodes.append({
            "name": b["id"], "mesh": kinds.index(b["kind"]),
            "translation": [round((x0 + x1) / 2, 3), 0, round((z0 + z1) / 2, 3)],
            "scale": [round(x1 - x0, 3), b["h"], round(z1 - z0, 3)],
        })  # fmt: skip
    doc = {
        "asset": {"version": "2.0", "generator": "vigil demo/synthetic/build.py (synthetic)"},
        "scene": 0,
        "scenes": [{"name": "synthetic site plan", "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(binary)}],
    }
    js = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(js), b"JSON")
        + js
        + struct.pack("<I4s", len(binary), b"BIN\x00")
        + binary
    )


# ---------------------------------------------------------------------------
# Presets for the live buttons (cached results shown when live is unavailable)
# ---------------------------------------------------------------------------


def build_presets(protected: dict[str, ProtectedObject]) -> dict[str, Any]:
    def bin_box() -> dict[str, Any]:
        cam = PinholeCam(CAMERA_POSES["side_right"])
        b = next(x for x in BOXES if x["id"] == "bin")
        shape = project_block(cam, *b["min"], *b["max"], b["h"])
        assert shape is not None, "bin must be visible on side_right"
        return shape

    def gate_box() -> dict[str, Any]:
        cam = PinholeCam(CAMERA_POSES["side_left"])
        b = next(x for x in BOXES if x["id"] == "side_gate")
        shape = project_block(cam, *b["min"], *b["max"], b["h"])
        assert shape is not None
        return shape

    bin_shape, gate_shape = bin_box(), gate_box()

    def centre(box):
        return [round((box[0] + box[2]) / 2), round((box[1] + box[3]) / 2)]

    bin_fp = [[-8.4, 4.3], [-7.8, 4.3], [-7.8, 4.9], [-8.4, 4.9]]
    gate = protected["po_side_gate"]
    protect = [
        {"camera_id": "side_right", "point": centre(bin_shape["box"]), "label": "recycling bin",
         "object": {"id": "po_bin", "camera_id": "side_right", "label": "recycling bin",
                    "bbox": dict(zip(("x1", "y1", "x2", "y2"), bin_shape["box"], strict=True)),
                    "footprint": bin_fp, "call_id": "call_rec_0101"},
         "outline": bin_shape["outline"], "model": SAM, "call_id": "call_rec_0101",
         "latency_ms": 3120, "cost_usd": 0.0025, "recorded_at": "2026-10-31T15:12:00-07:00"},
        {"camera_id": "side_left", "point": centre(gate_shape["box"]), "label": "side gate",
         "object": {"id": gate.id, "camera_id": gate.camera_id, "label": gate.label,
                    "bbox": gate.bbox.model_dump(),
                    "footprint": [list(p) for p in gate.footprint or []],
                    "call_id": gate.call_id},
         "outline": gate_shape["outline"], "model": SAM, "call_id": gate.call_id,
         "latency_ms": 2870, "cost_usd": 0.0025, "recorded_at": "2026-10-29T16:20:00-07:00"},
    ]  # fmt: skip
    compile_ = [
        {"text": "tell me if anyone touches the bin after 9 PM", "transcript": None,
         "rule": Rule(id="r8", name="Recycling bin after 9 PM",
                      target=RuleTarget(kind="protected_object", id="po_bin"), trigger="touch",
                      active=ActiveWindow(start="21:00", end="06:00"),
                      severity="needs_attention", state="draft").model_dump(),
         "limits_note": ["Vigil doesn't identify people, so this applies to anyone.",
                         "'After 9 PM' is read as 21:00 to 06:00; change the end time if you "
                         "meant something else."],
         "model": SPARK, "call_id": "call_rec_0102", "latency_ms": 1840, "cost_usd": 0.0012,
         "recorded_at": "2026-10-31T15:14:00-07:00"},
        {"text": "tell me if anyone except family opens the side gate after 10 PM",
         "transcript": None,
         "rule": Rule(id="r9", name="Side gate after 10 PM (anyone)",
                      target=RuleTarget(kind="protected_object", id="po_side_gate"),
                      trigger="touch", active=ActiveWindow(start="22:00", end="06:00"),
                      severity="needs_attention", state="draft").model_dump(),
         "limits_note": ["Vigil doesn't identify people, so this applies to anyone. "
                         "The exception 'except family' was dropped."],
         "model": SPARK, "call_id": "call_rec_0104", "latency_ms": 1910, "cost_usd": 0.0012,
         "recorded_at": "2026-10-31T15:16:00-07:00"},
    ]  # fmt: skip
    rerun_c = [
        s(f"A person came along the front of the house and into the left side yard at "
          f"{clock(15186)}.", ["e15", "e16"]),
        s(f"At {clock(15245)} they touched the side gate.", ["e17"]),
        GAP_SENTENCE,
        s(f"They reappeared on the Left side camera at {clock(15304)} and went back through "
          f"the side gate.", ["e19", "e20"]),
        s(f"They were last seen leaving past the Front entrance camera at {clock(15385)}.",
          ["e22", "e23"]),
    ]  # fmt: skip
    rerun_b = [
        s(f"At {clock(5462)} a person came up to the porch on the Front entrance camera.",
          ["e5", "e6"]),
        s(f"They spent about 18 s on the porch, and a package was there from {clock(5494)}.",
          ["e7", "e9"]),
        s(f"They walked away at {clock(5520)}, leaving the package on the porch.", ["e8", "e9"]),
    ]  # fmt: skip
    rerun = {
        "v_c": {"story": [x.model_dump() for x in rerun_c], "verdict": "needs_attention",
                "validation": {"passed": True, "attempt": 1, "failures": []},
                "model": WONDER, "call_id": "call_rec_0103", "latency_ms": 21400,
                "cost_usd": 0.0412, "recorded_at": "2026-10-31T15:20:00-07:00"},
        "v_b": {"story": [x.model_dump() for x in rerun_b], "verdict": "noteworthy",
                "validation": {"passed": True, "attempt": 1, "failures": []},
                "model": WONDER, "call_id": "call_rec_0105", "latency_ms": 17300,
                "cost_usd": 0.0391, "recorded_at": "2026-10-31T15:22:00-07:00"},
        "v_a": {"story": [x.model_dump() for x in STORY_A], "verdict": "normal",
                "validation": {"passed": True, "attempt": 1, "failures": []},
                "model": None, "call_id": None, "latency_ms": 0, "cost_usd": 0.0,
                "note": "Not escalated, so the story is a template; a re-run gives the same text.",
                "recorded_at": "2026-10-31T15:24:00-07:00"},
    }  # fmt: skip
    return {"protect": protect, "compile": compile_, "rerun": rerun}


EVAL_PLACEHOLDER = {
    "synthetic": True,
    "status": "not measured",
    "note": "Pre-registered targets only. `vigil eval` appends measured results (FR-024); "
    "this synthetic bundle has none.",
    "targets": [
        {"metric": "Alert reduction", "target": ">= 80%", "result": None},
        {"metric": "Correct verdicts", "target": ">= 10 of 12", "result": None},
        {"metric": "Link precision", "target": ">= 90%", "result": None},
        {"metric": "Claims inside gaps", "target": "0", "result": None},
        {"metric": "Uncited sentences shipped", "target": "0", "result": None},
        {"metric": "3D position error (median, within 10 m)", "target": "< 0.5 m",
         "result": None},
        {"metric": "Test points inside stated r95", "target": ">= 90%", "result": None},
    ],
}  # fmt: skip


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def load_config() -> Config:
    raw = yaml.safe_load((REPO_ROOT / "config" / "cameras.yaml").read_text(encoding="utf-8"))
    return Config.model_validate(raw)


def build(out: Path | None = None) -> Path:
    out = Path(out) if out is not None else HERE
    config = load_config()
    ledger = Ledger()
    gate = ProtectedObject(
        id="po_side_gate", camera_id="side_left", label="side gate",
        bbox=Box(x1=800, y1=400, x2=880, y2=660),
        footprint=[(5.5, 2.95), (6.7, 2.95), (6.7, 3.05), (5.5, 3.05)],
        call_id=None, created_at=datetime.fromisoformat("2026-10-29T16:20:00-07:00"),
    )  # fmt: skip
    gate.call_id = ledger.add(SAM, "protect", None, "po_side_gate", -91200, latency_ms=2870,
                              units=1, cost_usd=0.0025)  # fmt: skip
    windows = build_windows_and_calls(ledger)
    trace = build_calls(ledger)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "synthetic.db"
        conn = db.open_db(db_path)
        for cam in config.cameras:
            db.insert_camera(conn, cam)
        for w in windows:
            db.insert_window(conn, w)
        appearance_calls = {c.req_hash: c.id for c in ledger.calls if c.purpose == "appearance"}
        colours = {"t_a1": ("navy", "grey"), "t_b1": ("brown", "brown"),
                   "t_c0": ("black", "grey"), "t_c1": ("black", "grey"),
                   "t_c2": ("black", "grey"), "t_c3": ("black", "grey")}  # fmt: skip
        for tid, spec in TRACKS.items():
            t0, t1 = spec["path"][0][0], spec["path"][-1][0]
            wids = [w.id for w in windows if w.camera_id == spec["camera"]
                    and w.status == "processed" and w.t0 < t1 and w.t1 > t0]  # fmt: skip
            track = Track(id=tid, camera_id=spec["camera"], cls=spec["cls"], t_first=t0,
                          t_last=t1, window_ids=wids, tag=spec["tag"])  # fmt: skip
            db.insert_track(conn, track, overlay_path=f"overlays.json#{spec['camera']}/{tid}",
                            sam_obj_ids={w: 1 for w in wids})  # fmt: skip
            for p in positions_for(tid):
                db.insert_position(conn, p)
            req = hashlib.sha256(f"{SPARK}|appearance|{tid}".encode()).hexdigest()[:16]
            if spec["cls"] == "person":
                up, low = colours[tid]
                carrying = ["box"] if tid == "t_b1" else []
                note = Appearance(tag=spec["tag"], **{"class": "person"}, upper_color=up,
                                  lower_color=low, carrying=carrying)  # fmt: skip
                db.insert_appearance(conn, tid, note, appearance_calls[req])
            elif spec["cls"] == "car":
                note = Appearance(tag=spec["tag"], **{"class": "vehicle"},
                                  vehicle_color="white", vehicle_body="hatchback")  # fmt: skip
                db.insert_appearance(conn, tid, note, appearance_calls[req])
        for e in EVENTS:
            db.insert_event(conn, e)
        for g in GAPS:
            db.insert_gap(conn, g)
        for v in VISITS:
            db.insert_visit(conn, v)
        db.insert_protected_object(conn, gate)
        rules = [
            (Rule(id="r1", name="Watched package removed",
                  target=RuleTarget(kind="watch", id="any"), trigger="removed",
                  severity="needs_attention"), "default"),
            (Rule(id="r2", name="Anyone in the backyard 23:00 to 05:00",
                  target=RuleTarget(kind="zone", id="backyard"), trigger="enter",
                  active=ActiveWindow(start="23:00", end="05:00"),
                  severity="needs_attention"), "default"),
            (Rule(id="r7", name="Side gate after 10 PM",
                  target=RuleTarget(kind="protected_object", id="po_side_gate"),
                  trigger="touch", active=ActiveWindow(start="22:00", end="06:00"),
                  severity="needs_attention"), "owner"),
        ]  # fmt: skip
        for rule, source in rules:
            db.insert_rule(conn, rule, source, "2026-10-29T16:25:00-07:00")
        db.insert_rule_hit(conn, RuleHit(rule_id="r7", visit_id="v_c", event_id="e17"))
        db.insert_watch(
            conn,
            Watch(id="w2", camera_id="front", phrase="package", origin="wonder",
                  status="watching", expires_at=iso(5530 + 86400), source_visit_id="v_b",
                  reason="e9: a package appeared on the porch"),
        )  # fmt: skip
        for call in ledger.calls:
            db.insert_model_call(conn, call)
        db.insert_validation(conn, "v_b", ValidationResult(passed=True, attempt=1))
        db.insert_validation(
            conn, "v_c", ValidationResult(passed=False, attempt=1, failures=REJECTION_C)
        )
        db.insert_validation(conn, "v_c", ValidationResult(passed=True, attempt=2))
        conn.commit()
        conn.close()

        overlays: dict[str, Any] = {}
        for tid, spec in TRACKS.items():
            overlays.setdefault(spec["camera"], {})[tid] = overlays_for(tid)
        presets = build_presets({"po_side_gate": gate})
        export_bundle(
            out,
            db_path,
            config=config,
            twin=build_twin(config, [gate]),
            overlays=overlays,
            presets=presets,
            trace=trace,
            eval_results=EVAL_PLACEHOLDER,
            media={"ground.glb": build_glb()},
            meta={
                "synthetic": True,
                "label": LABEL,
                "session_start": SESSION_START.isoformat(),
                "timezone": config.timezone,
                "scenario_titles": TITLES,
                "notes": [
                    "Every scene, person, path and number in this bundle is invented.",
                    "Camera views are drawn in the browser from overlays.json; no video.",
                    "Model and call IDs mirror the real ledger format; no call was made.",
                ],
            },
        )
    return out


if __name__ == "__main__":
    print(build())
