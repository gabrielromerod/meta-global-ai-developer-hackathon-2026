"""Shared contracts for every Vigil module (spec sections 9.3 and 9.4).

Owned by the integrator. Workstream code imports from here and never redefines these
types. Times are seconds on the aligned session clock (spec 9.3); pixel coordinates are
in the processed window's frame (at most 1280 px wide); world coordinates are metres in
the house frame (origin at the front-door marker, +X along the front wall, +Y up, glTF).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

Severity = Literal["normal", "noteworthy", "needs_attention"]
"""Rule severities and the verdict floor. Only rules can produce needs_attention."""

Verdict = Literal["normal", "noteworthy", "needs_attention", "cant_confirm"]
VerdictProposal = Literal["normal", "noteworthy"]
"""Wonder may only propose these two (spec 9.4 Story contract)."""

EventType = Literal["enter", "exit", "cross", "touch", "removed", "dwell"]
GapKind = Literal["blind_spot", "ambiguous_link", "outage"]
RuleTrigger = Literal["touch", "cross", "enter", "removed", "dwell"]
TargetKind = Literal["protected_object", "zone", "line", "watch"]
RuleState = Literal["draft", "active", "disabled", "discarded"]
WatchStatus = Literal["proposed", "rejected", "watching", "revoked", "expired"]
WatchOrigin = Literal["wonder", "owner"]
WindowStatus = Literal["pending", "idle", "processed", "failed"]
WindowTrigger = Literal["motion", "camera_ai", "manual"]
VisitState = Literal[
    "open", "in_gap", "closed", "triaged", "templated", "drafted", "validated", "published"
]
PositionMethod = Literal["footpoint", "height_prior", "fused"]
SentenceSource = Literal["wonder", "template", "code"]
TrackClass = Literal["person", "car", "package", "object"]
ZoneKind = Literal["egress", "perimeter", "interior_yard"]
"""egress: a door of the house itself; perimeter: where outsiders enter; else interior_yard."""
ActorRole = Literal["household_insider", "expected_visitor", "external_visitor", "unknown"]
"""Spatial-origin role of a subject (FR-044). Never an identity; unknown fails closed."""
AppliesTo = Literal["anyone", "external_visitor_only", "non_household"]
Funding = Literal["credit", "paid"]
IntrinsicsSource = Literal["fov_nominal", "lens_profile"]

APPLIES_TO_ROLES: dict[str, frozenset[str]] = {
    "anyone": frozenset({"household_insider", "expected_visitor", "external_visitor", "unknown"}),
    "non_household": frozenset({"expected_visitor", "external_visitor", "unknown"}),
    "external_visitor_only": frozenset({"external_visitor", "unknown"}),
}
"""Which actor roles each applies_to value fires on (spec 9.4 table); unknown always fires."""
CameraModel = Literal["pinhole", "fisheye"]
SamBackend = Literal["local", "api", "remote"]
TriageBackend = Literal["glimmer", "spark"]

SEVERITY_ORDER: dict[str, int] = {"normal": 0, "noteworthy": 1, "needs_attention": 2}

Point = tuple[float, float]
Polygon = list[Point]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=False)


# ---------------------------------------------------------------------------
# Configuration (config/cameras.yaml) — FR-001, FR-030, FR-038
# ---------------------------------------------------------------------------


class CameraSource(_Model):
    """Where the edge machine reads a camera. Credentials never live here (spec 6)."""

    host_env: str | None = None
    """Name of the env var holding the camera or NVR host, e.g. REOLINK_SIDE_LEFT_HOST."""
    channel: int | None = None
    """NVR channel (1-based) when the camera is behind a Reolink NVR."""
    stream: Literal["main", "sub"] = "main"


class CameraCfg(_Model):
    id: str
    name: str
    source: CameraSource | None = None
    width: int = 1280
    height: int = 720
    offset_s: float = 0.0
    """Clock offset from the sync clap (FR-002), added to camera time to get session time."""
    zones: dict[str, Polygon] = Field(default_factory=dict)
    lines: dict[str, list[Point]] = Field(default_factory=dict)
    exits: dict[str, Polygon] = Field(default_factory=dict)
    privacy: list[Polygon] = Field(default_factory=list)
    """Pixel polygons blacked out before anything is stored for upload (FR-003)."""
    motion_threshold: float | None = None
    """Fraction in [0, 1] of unmasked pixels changed between 0.2 s samples (FR-005).

    None uses the ingest default (0.002). The loader rejects values outside [0, 1].
    """
    zone_kinds: dict[str, ZoneKind] = Field(default_factory=dict)
    """Zone id -> kind (FR-008 origin tagging). Zones without an entry are interior_yard."""
    hfov_deg: float | None = None
    """Nominal horizontal field of view from the camera model's datasheet (FR-036)."""

    @model_validator(mode="before")
    @classmethod
    def _zones_with_kinds(cls, data: object) -> object:
        """Accept spec 9.4 zones `{kind, polygon}` as well as plain polygon lists."""
        if not isinstance(data, dict) or not isinstance(data.get("zones"), dict):
            return data
        zones: dict[str, object] = {}
        kinds: dict[str, object] = dict(data.get("zone_kinds") or {})
        for zid, value in data["zones"].items():
            if isinstance(value, dict):
                zones[zid] = value.get("polygon")
                if "kind" in value:
                    kinds[zid] = value["kind"]
            else:
                zones[zid] = value
        return {**data, "zones": zones, "zone_kinds": kinds}

    def zone_kind(self, zone_id: str) -> ZoneKind:
        return self.zone_kinds.get(zone_id, "interior_yard")


class BlindRegion(_Model):
    id: str
    name: str
    polygon_m: list[Point]
    """Ground polygon in world metres (x, z), written by `vigil spatial coverage`."""


class TopologyEdge(_Model):
    from_: str = Field(alias="from")
    to: str
    exit: str | None = None
    min_s: float | None = None
    max_s: float | None = None
    blind: bool = False


class Config(_Model):
    timezone: str = "America/Los_Angeles"
    cameras: list[CameraCfg]
    blind_regions: list[BlindRegion] = Field(default_factory=list)
    topology: list[TopologyEdge] = Field(default_factory=list)

    def camera(self, camera_id: str) -> CameraCfg:
        for cam in self.cameras:
            if cam.id == camera_id:
                return cam
        raise KeyError(camera_id)


# ---------------------------------------------------------------------------
# Ingest and perception — FR-004 to FR-008
# ---------------------------------------------------------------------------


class Window(_Model):
    id: str
    camera_id: str
    t0: float
    t1: float
    path: str | None = None
    file_id: str | None = None
    motion: float | None = None
    trigger: WindowTrigger | None = None
    status: WindowStatus = "pending"
    fps: float = 10.0
    width: int = 1280
    height: int = 720


class Box(_Model):
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def iou(self, other: Box) -> float:
        ix = max(0.0, min(self.x2, other.x2) - max(self.x1, other.x1))
        iy = max(0.0, min(self.y2, other.y2) - max(self.y1, other.y1))
        inter = ix * iy
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


class SamFrame(_Model):
    frame: int
    t: float
    box: Box
    mask_rle: str | None = None
    """COCO RLE (counts string) of the full-frame mask, when present."""
    confidence: float | None = None


class SamObject(_Model):
    """One SAM 3.1 object id inside one window for one noun phrase (FR-006)."""

    window_id: str
    camera_id: str
    phrase: str
    obj_id: int
    frames: list[SamFrame]
    width: int | None = None
    """Frame size of the media SAM saw (the box/mask w and h), when known."""
    height: int | None = None


class TrackFrame(_Model):
    t: float
    box: Box
    mask_rle: str | None = None
    confidence: float | None = None
    clipped: bool = False
    """Mask touches the image's bottom edge or is truncated (feet hidden; FR-039 step 3)."""


class Track(_Model):
    id: str
    camera_id: str
    cls: TrackClass
    t_first: float
    t_last: float
    frames: list[TrackFrame] = Field(default_factory=list)
    window_ids: list[str] = Field(default_factory=list)
    tag: str | None = None
    """Burned-in tag shown to Spark, e.g. "T3" (FR-009)."""
    phrase: str | None = None
    """SAM noun phrase that produced the track (distinguishes watches mapped to "object")."""
    origin_zone: str | None = None
    """Zone where the track was born (FR-008): majority foot point of its first 10 frames;
    None when observation was interrupted in the 2 s before or an egress origin was voided."""


class Event(_Model):
    id: str
    visit_id: str | None = None
    camera_id: str
    track_id: str
    type: EventType
    t0: float
    t1: float
    target: str | None = None
    """Protected object, zone, line or watch id the event refers to, if any."""
    clip_t0: float
    clip_t1: float
    subject_id: str | None = None
    actor_role: ActorRole | None = None
    """Filled in after visit assembly from the event's subject chain (FR-044)."""


class CameraAiEvent(_Model):
    """Reolink on-camera AI event (FR-032). Presence only: no box, no position."""

    id: str
    camera_id: str
    kind: Literal["person", "vehicle", "pet", "motion"]
    t0: float
    t1: float | None = None


# ---------------------------------------------------------------------------
# Appearance notes (Muse Spark) — FR-009, NFR-003
# ---------------------------------------------------------------------------

COLORS: tuple[str, ...] = (
    "black", "white", "grey", "red", "orange", "yellow", "green", "blue", "navy",
    "purple", "pink", "brown", "beige", "unknown",
)  # fmt: skip

VehicleBody = Literal["sedan", "suv", "pickup", "van", "hatchback", "truck", "motorcycle", "other"]


class Appearance(_Model):
    """No face, age, gender, skin or ethnicity fields exist, by design (NFR-003)."""

    tag: str
    class_: Literal["person", "vehicle", "object"] = Field(alias="class")
    upper_color: str | None = None
    lower_color: str | None = None
    carrying: list[str] = Field(default_factory=list)
    vehicle_color: str | None = None
    vehicle_body: VehicleBody | None = None

    @field_validator("upper_color", "lower_color", "vehicle_color")
    @classmethod
    def _known_color(cls, v: str | None) -> str | None:
        if v is not None and v not in COLORS:
            raise ValueError(f"colour {v!r} not in the fixed list")
        return v


# ---------------------------------------------------------------------------
# Owner objects, rules and watches — FR-012, FR-019, FR-020, FR-021
# ---------------------------------------------------------------------------


class ProtectedObject(_Model):
    id: str
    camera_id: str
    label: str
    mask_path: str | None = None
    bbox: Box
    footprint: list[Point] | None = None
    """Ground footprint in world metres, projected via calibration (step 5 of the demo)."""
    call_id: str | None = None
    created_at: datetime | None = None


class Watch(_Model):
    id: str
    camera_id: str
    phrase: str
    origin: WatchOrigin
    status: WatchStatus
    expires_at: datetime | None = None
    source_visit_id: str | None = None
    reason: str | None = None


class RuleTarget(_Model):
    kind: TargetKind
    id: str


class ActiveWindow(_Model):
    start: str
    """Local "HH:MM". A window whose end is before its start crosses midnight."""
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        hh, _, mm = v.partition(":")
        if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) < 24 and 0 <= int(mm) < 60):
            raise ValueError(f"expected HH:MM, got {v!r}")
        return v


class Rule(_Model):
    id: str
    name: str
    target: RuleTarget
    trigger: RuleTrigger
    min_dwell_s: float | None = None
    active: ActiveWindow | None = None
    """None means always active."""
    severity: Severity
    applies_to: AppliesTo = "anyone"
    """Which spatial-origin roles the rule fires on (spec 9.4 table, FR-012). Never a person."""
    state: RuleState = "active"


class Subject(_Model):
    """One subject chain in a visit: linked tracks plus its spatial-origin role (FR-044)."""

    id: str
    visit_id: str | None = None
    track_ids: list[str]
    actor_role: ActorRole
    role_basis: str
    """egress:<zone> | checkin:<id> | window:<id> | perimeter:<zone> | group:<role> |
    gap_unresolved:<gap_id> | ambiguous_link:<track_id> | origin_null:<track_id>"""


class ExpectedWindow(_Model):
    """Owner-set Expected Guest / Delivery Window (FR-029): set in advance, at most 12 h."""

    id: str
    label: str | None = None
    start: datetime
    end: datetime
    cameras: list[str] = Field(default_factory=list)
    zones: list[str] = Field(default_factory=list)
    state: Literal["scheduled", "active", "expired", "cancelled"] = "scheduled"
    created_at: datetime | None = None
    """When the owner set the window. A track counts only if it starts at or after both
    start and created_at, so a window is never retroactive (FR-029)."""

    @model_validator(mode="after")
    def _max_12h(self) -> ExpectedWindow:
        if self.end <= self.start:
            raise ValueError("window end must be after its start")
        if (self.end - self.start).total_seconds() > 12 * 3600:
            raise ValueError("expected windows are capped at 12 h (FR-029)")
        return self


class CheckIn(_Model):
    """Explicit "I'm outside" tap (FR-044 step 2): single-use, never retroactive."""

    id: str
    session_id: str | None = None
    start: datetime
    expires: datetime
    bound_subject: str | None = None
    revoked: bool = False


class RuleHit(_Model):
    rule_id: str
    visit_id: str
    event_id: str


class RuleResult(_Model):
    hits: list[RuleHit] = Field(default_factory=list)
    floor: Severity = "normal"
    scoped_out: list[str] = Field(default_factory=list)
    """Event ids whose household touch every in-force rule excluded (spec 9.4 case 2)."""


# ---------------------------------------------------------------------------
# Gaps, visits, stories, verdicts — FR-010 to FR-016
# ---------------------------------------------------------------------------


class Gap(_Model):
    id: str
    visit_id: str
    kind: GapKind
    t0: float
    t1: float
    from_camera: str | None = None
    to_camera: str | None = None
    region_id: str | None = None
    resolved: bool = False
    """True when the subject was re-linked after the gap (it is still a gap: nothing was seen)."""

    @property
    def duration_s(self) -> float:
        return self.t1 - self.t0


class StorySentence(_Model):
    text: str
    event_ids: list[str] = Field(default_factory=list)
    source: SentenceSource = "wonder"
    gap_id: str | None = None
    """Set on code-written gap sentences."""
    model: str | None = None
    """Model id that wrote the sentence (NFR-022); None for template and code sentences."""
    call_id: str | None = None
    """Ledger call id that produced the sentence (NFR-022)."""


class GapPlacement(_Model):
    gap_id: str
    after: int
    """Index of the sentence the code-written gap sentence follows."""


class WatchProposal(_Model):
    camera_id: str
    phrase: str
    reason_event_id: str


class StoryDraft(_Model):
    verdict_proposal: VerdictProposal | None = None
    sentences: list[StorySentence]
    gap_after_sentence: list[GapPlacement] = Field(default_factory=list)
    watch_proposals: list[WatchProposal] = Field(default_factory=list)


class ValidationFailure(_Model):
    check: Literal[
        "schema", "sentence_count", "uncited", "foreign_event", "time_mismatch",
        "time_in_gap", "camera_mismatch", "banned_word", "unknown_gap", "role_claim",
    ]  # fmt: skip
    sentence_index: int | None = None
    detail: str


class ValidationResult(_Model):
    passed: bool
    failures: list[ValidationFailure] = Field(default_factory=list)
    attempt: int = 1


class TriageDecision(_Model):
    escalate: bool
    forced: bool
    reason: str
    source: Literal["code", "glimmer", "spark"]


class Visit(_Model):
    id: str
    scenario: str | None = None
    t0: float
    t1: float
    state: VisitState = "open"
    track_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    floor: Severity = "normal"
    proposal: VerdictProposal | None = None
    verdict: Verdict | None = None
    escalated: bool | None = None
    story: list[StorySentence] = Field(default_factory=list)


class VisitLedger(_Model):
    """Everything Wonder and the validator see for one visit: JSON only, no pixels (5.8)."""

    visit: Visit
    events: list[Event]
    gaps: list[Gap] = Field(default_factory=list)
    protected_objects: list[ProtectedObject] = Field(default_factory=list)
    rule_hits: list[RuleHit] = Field(default_factory=list)
    appearance: dict[str, Appearance] = Field(default_factory=dict)
    """Keyed by track id."""
    camera_names: dict[str, str] = Field(default_factory=dict)
    """camera_id -> display name, used by validator check 4."""
    region_names: dict[str, str] = Field(default_factory=dict)
    subjects: list[Subject] = Field(default_factory=list)
    """Subject chains with roles; validator check 7 matches role phrases against them."""
    """blind region id -> display name (e.g. shed_back -> "behind the shed"), for gap sentences."""
    timezone: str = "America/Los_Angeles"
    session_start: datetime | None = None
    """Wall-clock time of session t=0, for rendering and checking clock times."""


class VisitSummary(_Model):
    """Compact triage input (FR-013)."""

    visit_id: str
    cameras: list[str]
    event_types: list[EventType]
    rule_fired: bool
    protected_touched: bool
    unresolved_gap: bool
    new_object: bool = False
    duration_s: float


# ---------------------------------------------------------------------------
# Spatial — FR-035 to FR-039
# ---------------------------------------------------------------------------


class Intrinsics(_Model):
    model: CameraModel = "pinhole"
    k: list[list[float]]
    """3x3 camera matrix."""
    dist: list[float] = Field(default_factory=list)
    width: int
    height: int
    rms_px: float | None = None
    fov_fallback: bool = False
    """True when focal length came from the lens field of view (flagged low accuracy)."""
    source: IntrinsicsSource = "lens_profile"
    """fov_nominal: focal length from the datasheet HFOV, no distortion (primary, flagged);
    lens_profile: checkerboard RMS < 1 px, recorded once per camera model (FR-036)."""


class Extrinsics(_Model):
    rvec: list[float]
    """Rodrigues rotation, world -> camera."""
    tvec: list[float]
    reproj_mean_px: float | None = None
    heldout_ground_m: float | None = None
    method: Literal["pnp_ransac", "homography"] = "pnp_ransac"


class Calibration(_Model):
    camera_id: str
    intrinsics: Intrinsics
    extrinsics: Extrinsics
    date: str | None = None


class Position(_Model):
    track_id: str
    t: float
    x: float
    y: float
    z: float
    r95: float
    """95% horizontal uncertainty radius in metres."""
    method: PositionMethod
    cameras: list[str]
    flags: list[str] = Field(default_factory=list)
    """e.g. "low_confidence", "inconsistent"."""


# ---------------------------------------------------------------------------
# Model calls, ledger and budget — FR-023, FR-043
# ---------------------------------------------------------------------------


class ModelCall(_Model):
    id: str
    model: str
    purpose: str
    visit_id: str | None = None
    req_hash: str
    latency_ms: int | None = None
    in_tokens: int | None = None
    out_tokens: int | None = None
    units: float | None = None
    """Billed units other than tokens: frames, images or audio seconds."""
    cost_usd: float = 0.0
    cached: bool = False
    ok: bool = True
    error: str | None = None
    backend: str = "api"
    feature: str | None = None
    """Budget feature this call is charged to (spec 11.4), so per-feature caps survive restarts."""
    funding: Funding = "credit"
    """credit: inside the credit window ($140 cap); paid: after it, judging cap (NFR-036/037)."""
    gpu_s: float | None = None
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _no_contributor(self) -> ModelCall:
        if self.model.endswith("contributor") or "contributor" in self.model.split("-"):
            raise ValueError("Contributor-mode model IDs are forbidden (NFR-004)")
        return self


class CostEstimate(_Model):
    model: str
    feature: str
    usd: float
    in_tokens: int = 0
    out_tokens: int = 0
    frames: int = 0
    images: int = 0
    audio_s: float = 0.0
