"""Builders for synthetic scenarios A, A′, B, B′ and C (spec 4 "The recorded evening").

Nothing here is footage. Every subject is a box moving along authored keyframes in the
processed 1280x720 frame of ``config/cameras.yaml``. The SAM 3.1 answers are rendered at test
time in the documented wire grammar (box record plus a one-bit mask record, encoded with
meta-sam-parser's own codec as in ``tests/fixtures/meta/sam_make_fixtures.py``), so the golden
pipeline parses them with ``vigil.meta.sam`` like a recorded response. Mask rasters are sent at
1/5 of the box size (the parser scales a mask to its box), which keeps the pure-Python mask
codec fast enough for CI.

The other model answers are recorded-style fakes that only read what the real model would
get: Spark notes per burned-in tag, a triage decision from the visit summary, and Wonder drafts
built from the visit ledger JSON (event ids are content hashes, so drafts look them up).

The evening is 2 November 2026 in Pacific standard time (DST ended on 1 November). Roles come
from where each person came from (FR-008 origins, FR-044), never from who they are:

- **A Routine** (front, 14:42): a person walks out of the front door (``front_door_egress``)
  to the driveway and gets into the parked car, which drives off. ``household_insider``
  (``egress:front_door_egress``). Expected: normal, templated, not escalated.
- **A′ Night** (front -> side_left -> front, 18:02): out of the front door again, round to the
  side gate, touches it inside r7's 17:30-06:00 window and goes back inside. r7 applies to
  ``non_household``, so it is in force but excluded (9.4 case 2). Expected: normal, not
  escalated, the exclusion in the trace.
- **B Delivery** (front, 15:31): a courier in from the street (``driveway_entry``) walks to
  the porch, leaves a box, walks away. ``external_visitor``. The recorded triage escalates
  (new object); Wonder proposes watching ``package`` on ``front``. Expected: noteworthy, watch
  accepted by the loop.
- **B′ Delivery inside a window** (front, 16:20): the same walk inside the owner's
  "deliveries" window w3 (16:00-16:45, front). ``expected_visitor`` (``window:w3``); Wonder
  proposes normal. Expected: normal.
- **C After dark** (side_left, 18:13:45): a person in from the side alley (``side_alley``)
  touches the protected side gate at 18:14:05, leaves through ``to_shed_back``, reappears 41 s
  later and leaves. ``external_visitor`` (``perimeter:side_alley``), carried across the gap
  (unambiguous re-link; the notes also agree on known colours). The first Wonder draft has an
  uncited sentence and is rejected; the retry passes. Expected: needs_attention, rule r7, one
  41 s blind-spot gap behind the shed.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from meta_sam_parser._mask_codec import _encode_raster  # fixture authoring only

from tests.fixtures.meta.sam_make_fixtures import ellipse_raster
from vigil.models import (
    Appearance,
    Calibration,
    CameraAiEvent,
    CheckIn,
    Event,
    ExpectedWindow,
    TriageDecision,
    VisitLedger,
    VisitSummary,
    Watch,
    Window,
)
from vigil.reasoning.clock import format_clock, to_local

HERE = Path(__file__).resolve().parent
LABELS_DIR = HERE / "labels"

PST = timezone(timedelta(hours=-8))
"""Pacific standard time on the session date (DST ended on 1 November 2026)."""
PDT = timezone(timedelta(hours=-7))
"""Pacific daylight time (before 1 November 2026); kept for tests that pin an older date."""
FPS = 10.0
STEP = 2
"""SAM records every 2nd frame (5 Hz), like the perception fixtures; the API may skip frames."""
PHRASES = ("person", "car")
CONFIDENCE = 0.9
MASK_SCALE = 5
"""Mask raster = box size / MASK_SCALE (an ellipse); the parser places it at box size."""
FRAME_W, FRAME_H = 1280, 720

Key = tuple[float, float, float]
"""(session time, foot x, foot y): the bottom-centre of the box at that time."""


# ---------------------------------------------------------------------------
# Subjects and SAM wire output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Subject:
    """One subject on one camera: a box of fixed size moving between keyframes."""

    camera_id: str
    phrase: str
    keys: tuple[Key, ...]
    width: int
    height: int

    @property
    def t_first(self) -> float:
        return self.keys[0][0]

    @property
    def t_last(self) -> float:
        return self.keys[-1][0]

    def foot(self, t: float) -> tuple[float, float] | None:
        if t < self.t_first - 1e-9 or t > self.t_last + 1e-9:
            return None
        if len(self.keys) == 1:
            return self.keys[0][1], self.keys[0][2]
        for (ta, xa, ya), (tb, xb, yb) in itertools.pairwise(self.keys):
            if ta - 1e-9 <= t <= tb + 1e-9:
                f = 0.0 if tb == ta else (t - ta) / (tb - ta)
                return xa + f * (xb - xa), ya + f * (yb - ya)
        return None  # pragma: no cover - keys are sorted

    def box_origin(self, t: float) -> tuple[int, int] | None:
        """Top-left pixel of the box at ``t`` (None when the subject is not in view)."""
        p = self.foot(t)
        if p is None:
            return None
        return round(p[0] - self.width / 2), round(p[1] - self.height)


_MASKS: dict[tuple[int, int], str] = {}


def _mask_payload(width: int, height: int) -> str:
    if (width, height) not in _MASKS:
        _MASKS[(width, height)] = _encode_raster(ellipse_raster(width, height), width, height)
    return _MASKS[(width, height)]


def record(obj_id: int, x1: int, y1: int, bw: int, bh: int, c: float) -> str:
    """One SAM object record: box (x2/y2 inclusive on the wire) plus a low-res mask."""
    mw, mh = max(4, bw // MASK_SCALE), max(4, bh // MASK_SCALE)
    return (
        f"{obj_id}<|box;x1={x1};y1={y1};x2={x1 + bw - 1};y2={y1 + bh - 1};"
        f"w={FRAME_W};h={FRAME_H};c={c:.2f}|>"
        f"<|mask;x=0;y=0;c={c:.2f};data={mh},{mw},{_mask_payload(mw, mh)}|>"
    )


def make_window(camera_id: str, t0: float, t1: float) -> Window:
    return Window(
        id=f"{camera_id}_{round(t0 * 1000):09d}",
        camera_id=camera_id,
        t0=t0,
        t1=t1,
        motion=0.05,
        trigger="motion",
        status="pending",
        fps=FPS,
    )


def sam_text(window: Window, subjects: Sequence[Subject], phrase: str) -> str:
    """SAM 3.1 video output for one window and one noun phrase, in the wire grammar.

    Object ids are only stable inside one response, so they depend on the window too (the
    stitcher has to join them by IoU). Zero matches give an empty answer.
    """
    mine = [s for s in subjects if s.camera_id == window.camera_id and s.phrase == phrase]
    lines: list[str] = []
    n_frames = round((window.t1 - window.t0) * window.fps)
    for frame in range(0, n_frames, STEP):
        t = round(window.t0 + frame / window.fps, 6)
        recs = []
        for i, s in enumerate(mine):
            origin = s.box_origin(t)
            if origin is None:
                continue
            obj_id = (i * 5 + int(window.t0)) % 16
            recs.append(record(obj_id, origin[0], origin[1], s.width, s.height, CONFIDENCE))
        if recs:
            lines.append(f"<{frame}f>" + ",".join(recs))
    return "\n".join(lines) + "\n" if lines else ""


# ---------------------------------------------------------------------------
# Recorded-style model fakes
# ---------------------------------------------------------------------------


class FakeSpark:
    """Appearance notes per burned-in tag (FR-009): colours by track class, nothing else."""

    def __init__(self, person: dict[str, Any], vehicle: dict[str, Any] | None = None) -> None:
        self.person = person
        self.vehicle = vehicle or {"vehicle_color": "white", "vehicle_body": "hatchback"}
        self.calls = 0

    def __call__(self, tracks: Sequence[Any]) -> dict[str, Appearance]:
        self.calls += 1
        out: dict[str, Appearance] = {}
        for t in tracks:
            if t.tag is None:
                continue
            if t.cls == "person":
                out[t.tag] = Appearance(tag=t.tag, **{"class": "person"}, **self.person)
            elif t.cls == "car":
                out[t.tag] = Appearance(tag=t.tag, **{"class": "vehicle"}, **self.vehicle)
        return out


class RecordedTriage:
    """A recorded Spark triage answer (FR-013); remembers every summary it was asked about."""

    def __init__(self, escalate: bool, reason: str) -> None:
        self.escalate = escalate
        self.reason = reason
        self.summaries: list[VisitSummary] = []

    def __call__(self, summary: VisitSummary) -> TriageDecision:
        self.summaries.append(summary)
        return TriageDecision(
            escalate=self.escalate, forced=False, reason=self.reason, source="spark"
        )


Draft = Callable[[VisitLedger], dict[str, Any]]


class ScriptedWonder:
    """Muse Wonder stand-in: returns the scripted drafts in order, built from the ledger."""

    def __init__(self, drafts: Sequence[Draft]) -> None:
        self.drafts = list(drafts)
        self.failures_seen: list[list[str] | None] = []

    @property
    def calls(self) -> int:
        return len(self.failures_seen)

    def __call__(self, ledger: VisitLedger, failures: list[str] | None) -> dict[str, Any]:
        n = len(self.failures_seen)
        self.failures_seen.append(None if failures is None else list(failures))
        if n >= len(self.drafts):
            raise RuntimeError("unexpected Wonder call")
        return self.drafts[n](ledger)


def clock(ledger: VisitLedger, t: float) -> str:
    assert ledger.session_start is not None
    return format_clock(to_local(ledger.session_start, t, ledger.timezone))


def pick(
    ledger: VisitLedger,
    type_: str,
    target: str | None = None,
    *,
    last: bool = False,
    after: float | None = None,
    before: float | None = None,
) -> Event:
    """The first (or last) event of a type/target in this visit, optionally in a time range."""
    evs = [
        e
        for e in sorted(ledger.events, key=lambda e: (e.t0, e.id))
        if e.type == type_
        and (target is None or e.target == target)
        and (after is None or e.t0 > after)
        and (before is None or e.t0 < before)
    ]
    if not evs:
        raise LookupError(f"no {type_} event on {target!r} in visit {ledger.visit.id}")
    return evs[-1] if last else evs[0]


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    id: str
    title: str
    session_start: datetime
    windows: list[Window]
    subjects: list[Subject]
    notes: FakeSpark
    triage: RecordedTriage | None
    writer: ScriptedWonder | None
    watches: list[Watch] = field(default_factory=list)
    camera_ai_events: list[CameraAiEvent] = field(default_factory=list)
    expected_windows: list[ExpectedWindow] = field(default_factory=list)
    """Owner-set Expected Guest / Delivery Windows (FR-029) in force for this session."""
    checkins: list[CheckIn] = field(default_factory=list)
    """Explicit "I'm outside" check-ins (FR-044 step 2) for this session."""

    def sam_outputs(self) -> dict[str, dict[str, str]]:
        """Recorded SAM answers: window id -> noun phrase -> wire text."""
        return {
            w.id: {p: sam_text(w, self.subjects, p) for p in PHRASES}
            for w in sorted(self.windows, key=lambda w: w.id)
        }

    def inputs(self) -> dict[str, Any]:
        """Pipeline inputs (vigil.pipeline.ScenarioInputs) as plain JSON-able data."""
        return {
            "scenario": self.id,
            "windows": [w.model_dump(mode="json") for w in self.windows],
            "sam_outputs": self.sam_outputs(),
            "camera_ai_events": [e.model_dump(mode="json") for e in self.camera_ai_events],
        }

    def session_json(self) -> dict[str, Any]:
        """The ``session.json`` extras ``vigil process`` reads (windows and check-ins)."""
        return {
            "session_start": self.session_start.isoformat(),
            "expected_windows": [w.model_dump(mode="json") for w in self.expected_windows],
            "checkins": [c.model_dump(mode="json") for c in self.checkins],
        }

    def label(self) -> dict[str, Any]:
        return load_label(self.id)


def load_label(scenario: str) -> dict[str, Any]:
    """Pre-registered eval label (schema eval/labels/_template.json) for a synthetic scenario.

    Keys starting with ``$`` are comments and are dropped, as ``vigil eval`` does."""
    raw = json.loads((LABELS_DIR / f"{scenario}.json").read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("$")}


def _at(hh: int, mm: int, ss: int = 0) -> datetime:
    """A wall-clock time on the recorded evening (2 November 2026, Pacific standard time)."""
    return datetime(2026, 11, 2, hh, mm, ss, tzinfo=PST)


def _person(camera_id: str, *keys: Key, height: int = 180) -> Subject:
    return Subject(camera_id, "person", tuple(keys), 60, height)


def _out_of_the_front_door(t: float) -> tuple[Key, ...]:
    """Born inside ``front_door_egress`` (held for over 1 s, FR-008 majority rule)."""
    return ((t, 630, 540), (t + 1.2, 630, 545))


def scenario_a() -> Scenario:
    """A Routine: out of the front door -> driveway -> into the parked car, which drives off."""
    person = _person("front", *_out_of_the_front_door(2.0), (6.0, 400, 580), (11.0, 250, 560))
    car = Subject("front", "car", ((0.0, 200, 580), (13.0, 200, 580), (22.0, 200, 200)), 260, 150)
    return Scenario(
        id="A",
        title="Routine: a person leaves by the front door and drives off",
        session_start=_at(14, 42),
        windows=[make_window("front", t0, t0 + 10.0) for t0 in (0.0, 8.0, 16.0)],
        subjects=[person, car],
        notes=FakeSpark({"upper_color": "navy", "lower_color": "grey"}),
        triage=RecordedTriage(False, "routine departure: a person and a car leave"),
        writer=ScriptedWonder([]),
        camera_ai_events=[
            CameraAiEvent(id="rl_a1", camera_id="front", kind="person", t0=2.5, t1=10.0)
        ],
    )


def scenario_a_prime() -> Scenario:
    """A′ Night: out of the front door, round to the side gate, touches it, back inside.

    Inside r7's 17:30-06:00 window, but r7 applies to ``non_household`` and this person came
    out of the house's own door (front -> side_left -> front, each hand-off 6 s on a
    non-blind 2-20 s edge), so r7 is in force and excluded: Normal, not escalated.
    """
    front_out = _person("front", *_out_of_the_front_door(2.0), (6.0, 1000, 600), (8.0, 1240, 600))
    gate = _person(
        "side_left",
        (14.0, 560, 690),
        (18.0, 800, 640),
        (21.0, 800, 640),
        (25.0, 560, 690),
        height=200,
    )
    front_in = _person("front", (31.0, 1240, 600), (34.0, 1000, 600), (37.0, 630, 545))
    windows = [make_window("front", t0, t0 + 10.0) for t0 in (0.0, 8.0, 30.0)]
    windows += [make_window("side_left", t0, t0 + 10.0) for t0 in (12.0, 20.0)]
    return Scenario(
        id="A-prime",
        title="Night: out of the front door, touches the side gate, back inside",
        session_start=_at(18, 2),
        windows=windows,
        subjects=[front_out, gate, front_in],
        notes=FakeSpark({"upper_color": "unknown", "lower_color": "unknown"}),
        triage=RecordedTriage(False, "a short walk round the house and back in"),
        writer=ScriptedWonder([]),
    )


COURIER_KEYS: tuple[Key, ...] = (
    (5.0, 90, 560),
    (6.2, 100, 560),
    (11.0, 640, 640),
    (15.0, 640, 640),
    (21.0, 150, 560),
)
"""B and B′: in from the street at ``driveway_entry`` (perimeter), to the porch and back."""


def _b_draft(ledger: VisitLedger) -> dict[str, Any]:
    first = pick(ledger, "enter", "driveway")
    porch_in = pick(ledger, "enter", "porch")
    porch_out = pick(ledger, "exit", "porch")
    gone = pick(ledger, "exit", "driveway", last=True)
    return {
        "verdict_proposal": "noteworthy",
        "sentences": [
            {
                "text": "Someone who arrived from outside the property walked up the driveway "
                f"to the porch on the Front entrance camera at {clock(ledger, porch_in.t0)}.",
                "event_ids": [first.id, porch_in.id],
            },
            {
                "text": "They left a box on the porch and walked back down the driveway.",
                "event_ids": [porch_out.id, gone.id],
            },
        ],
        "gap_after_sentence": [],
        "watch_proposals": [
            {"camera_id": "front", "phrase": "package", "reason_event_id": porch_in.id}
        ],
    }


def scenario_b() -> Scenario:
    """B Delivery: a courier from the driveway entry leaves a box on the porch."""
    return Scenario(
        id="B",
        title="Delivery: a courier leaves a box on the porch",
        session_start=_at(15, 31),
        windows=[make_window("front", t0, t0 + 10.0) for t0 in (0.0, 8.0, 16.0)],
        subjects=[_person("front", *COURIER_KEYS)],
        notes=FakeSpark({"upper_color": "brown", "lower_color": "brown", "carrying": ["box"]}),
        triage=RecordedTriage(True, "a new object: a box was left on the porch"),
        writer=ScriptedWonder([_b_draft]),
    )


DELIVERY_WINDOW = ExpectedWindow(
    id="w3",
    label="deliveries",
    start=_at(16, 0),
    end=_at(16, 45),
    cameras=["front"],
    state="active",
)
"""B′: the owner's "deliveries" window on the front camera, set before it started (FR-029)."""


def _b_prime_draft(ledger: VisitLedger) -> dict[str, Any]:
    first = pick(ledger, "enter", "driveway")
    porch_in = pick(ledger, "enter", "porch")
    porch_out = pick(ledger, "exit", "porch")
    gone = pick(ledger, "exit", "driveway", last=True)
    return {
        "verdict_proposal": "normal",
        "sentences": [
            {
                "text": "An expected visitor walked up the driveway to the porch on the Front "
                f"entrance camera at {clock(ledger, porch_in.t0)}.",
                "event_ids": [first.id, porch_in.id],
            },
            {
                "text": "They left a box on the porch and walked back down the driveway.",
                "event_ids": [porch_out.id, gone.id],
            },
        ],
        "gap_after_sentence": [],
        "watch_proposals": [],
    }


def scenario_b_prime(window: ExpectedWindow = DELIVERY_WINDOW) -> Scenario:
    """B′ Delivery inside the owner's delivery window: the courier is ``expected_visitor``."""
    return Scenario(
        id="B-prime",
        title="Delivery inside an expected window",
        session_start=_at(16, 20),
        windows=[make_window("front", t0, t0 + 10.0) for t0 in (0.0, 8.0, 16.0)],
        subjects=[_person("front", *COURIER_KEYS)],
        notes=FakeSpark({"upper_color": "brown", "lower_color": "brown", "carrying": ["box"]}),
        triage=RecordedTriage(True, "a new object: a box was left on the porch"),
        writer=ScriptedWonder([_b_prime_draft]),
        expected_windows=[window],
    )


GAP_C = (40.0, 81.0)
"""C: last seen leaving through to_shed_back at 40 s, back in view at 81 s (41 s)."""


def _c_rejected(ledger: VisitLedger) -> dict[str, Any]:
    touch = pick(ledger, "touch", "po_side_gate")
    return {
        "verdict_proposal": "noteworthy",
        "sentences": [
            {
                "text": f"A person touched the side gate at {clock(ledger, touch.t0)}.",
                "event_ids": [touch.id],
            },
            {"text": "They checked the shed door.", "event_ids": []},
        ],
        "gap_after_sentence": [],
        "watch_proposals": [],
    }


def _c_retry(ledger: VisitLedger) -> dict[str, Any]:
    t_gap0, t_gap1 = GAP_C
    came = pick(ledger, "enter", "side_alley")
    touch = pick(ledger, "touch", "po_side_gate")
    leave = pick(ledger, "exit", "to_shed_back", before=t_gap0 + 1.0, last=True)
    back = pick(ledger, "enter", "to_shed_back", after=t_gap1 - 1.0)
    out = pick(ledger, "exit", "side_yard", last=True)
    gap = next(g for g in ledger.gaps if g.visit_id == ledger.visit.id)
    return {
        "verdict_proposal": "noteworthy",
        "sentences": [
            {
                "text": "Someone who arrived from outside the property came into view on the "
                f"Left side camera at {clock(ledger, came.t0)}.",
                "event_ids": [came.id],
            },
            {
                "text": f"They touched the side gate at {clock(ledger, touch.t0)}.",
                "event_ids": [touch.id],
            },
            {
                "text": "They walked out of view towards the back of the shed.",
                "event_ids": [leave.id],
            },
            {
                "text": f"They came back into view at {clock(ledger, back.t0)} and left the "
                f"Left side camera's view at {clock(ledger, out.t1)}.",
                "event_ids": [back.id, out.id],
            },
        ],
        "gap_after_sentence": [{"gap_id": gap.id, "after": 2}],
        "watch_proposals": [],
    }


def scenario_c() -> Scenario:
    """C After dark: in from the side alley, gate touched at 18:14, 41 s behind the shed."""
    first = _person(
        "side_left",
        (14.0, 300, 640),
        (20.0, 790, 640),
        (24.0, 800, 640),
        (37.0, 1180, 640),
        (40.0, 1220, 640),
        height=200,
    )
    back = _person("side_left", (81.0, 1220, 640), (86.0, 1000, 640), (95.0, 300, 640), height=200)
    starts = (8.0, 16.0, 24.0, 32.0, 80.0, 88.0)
    return Scenario(
        id="C",
        title="After dark: side gate touched, 41 s behind the shed, leaves",
        session_start=_at(18, 13, 45),
        windows=[make_window("side_left", t0, t0 + 10.0) for t0 in starts],
        subjects=[first, back],
        notes=FakeSpark({"upper_color": "black", "lower_color": "grey"}),
        triage=RecordedTriage(False, "should never be asked: code forces escalation"),
        writer=ScriptedWonder([_c_rejected, _c_retry]),
        camera_ai_events=[
            CameraAiEvent(id="rl_c1", camera_id="side_left", kind="person", t0=14.5, t1=39.0)
        ],
    )


SCENARIOS: dict[str, Callable[[], Scenario]] = {
    "A": scenario_a,
    "A-prime": scenario_a_prime,
    "B": scenario_b,
    "B-prime": scenario_b_prime,
    "C": scenario_c,
}
"""The recorded evening (spec 4). Clock order: A 14:42, B 15:31, B′ 16:20, A′ 18:02, C 18:13."""


# ---------------------------------------------------------------------------
# Spatial: synthetic calibration and site-plan ground for C (FR-039)
# ---------------------------------------------------------------------------

SIDE_LEFT_POSE = {"position": (3.7, 2.6, 0.2), "look_at": (6.4, 0.0, 7.5), "hfov_deg": 85.0}
"""Same pose as the synthetic demo bundle (demo/synthetic/build.py)."""


def side_left_calibration(heldout_ground_m: float = 0.18) -> Calibration:
    """A pinhole calibration of side_left in the processed 1280x720 frame."""
    from vigil.spatial.geometry import look_at_extrinsics, pinhole_intrinsics

    f = 640.0 / math.tan(math.radians(SIDE_LEFT_POSE["hfov_deg"] / 2))
    ext = look_at_extrinsics(SIDE_LEFT_POSE["position"], SIDE_LEFT_POSE["look_at"])
    ext = ext.model_copy(update={"heldout_ground_m": heldout_ground_m, "reproj_mean_px": 2.6})
    return Calibration(
        camera_id="side_left",
        intrinsics=pinhole_intrinsics(1280, 720, f),
        extrinsics=ext,
        date="2026-10-30",
    )


def site_ground():
    """Flat site-plan ground (spec 7 fallback ladder, level 3) covering the yard."""
    from vigil.spatial.geometry import RaycastScene, plane_ground

    return RaycastScene(ground=plane_ground(-12.0, -12.0, 12.0, 16.0))


# ---------------------------------------------------------------------------
# One golden run
# ---------------------------------------------------------------------------


def run_golden(
    sc: Scenario, cfg: Any, rules: Sequence[Any], protected: Sequence[Any], *, spatial: bool = True
) -> dict[str, Any]:
    """Run the offline pipeline on a scenario with its recorded answers and fakes."""
    from vigil.pipeline import run_scenario
    from vigil.reasoning.loop import load_allowlist

    spatial_kw: dict[str, Any] = {}
    if spatial:
        spatial_kw = {"calibrations": [side_left_calibration()], "ground": site_ground()}
    return run_scenario(
        sc.inputs(),
        cfg=cfg,
        rules=list(rules),
        protected=list(protected),
        watches=list(sc.watches),
        session_start=sc.session_start,
        notes=sc.notes,
        writer=sc.writer,
        triage_model=sc.triage,
        allowlist=load_allowlist(),
        expected_windows=list(sc.expected_windows),
        checkins=list(sc.checkins),
        **spatial_kw,
    )
