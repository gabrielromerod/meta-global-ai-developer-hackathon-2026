"""Deterministic templated story (FR-013, FR-014): used for routine visits and as the fallback.

Every sentence cites the event it describes, names only that event's camera, states that
event's own clock time, and never describes identity: the subject is "a person" (then "they")
or "a vehicle". When the ledger backs it (validator check 7), a subject is introduced by its
role phrase instead, e.g. "Someone who arrived from outside the property"; a new subject
(another chain, or the part after a role-breaking gap) is introduced again rather than called
"they". The output passes the citation validator by construction (property-tested).
"""

from __future__ import annotations

from vigil.models import Event, StorySentence, VisitLedger
from vigil.reasoning.clock import format_clock, to_local
from vigil.reasoning.validator import ROLE_PHRASES, humanise_id, role_and_basis, subject_index

MAX_SENTENCES = 6
_PRIORITY = {"removed": 0, "touch": 1, "cross": 2, "dwell": 3, "enter": 4, "exit": 5}


def _visit_events(ledger: VisitLedger) -> list[Event]:
    v = ledger.visit
    ids = set(v.event_ids)
    evs = [
        e
        for e in ledger.events
        if e.id in ids or e.visit_id == v.id or (not ids and e.visit_id is None)
    ]
    return sorted(evs, key=lambda e: (e.t0, e.id))


def _select(events: list[Event], limit: int, vehicles: set[str] | None = None) -> list[Event]:
    """Keep the first and last events, then the most important ones, in time order.

    People come before vehicles: the story is about who came, not what was parked.
    """
    if len(events) <= limit:
        return events
    vehicles = vehicles or set()
    keep = {events[0].id, events[-1].id}
    rest = sorted(
        events[1:-1],
        key=lambda e: (e.track_id in vehicles, _PRIORITY.get(e.type, 9), e.t0, e.id),
    )
    for e in rest:
        if len(keep) >= limit:
            break
        keep.add(e.id)
    return [e for e in events if e.id in keep]


def _clock(ledger: VisitLedger, t: float) -> str:
    if ledger.session_start is None or ledger.session_start.utcoffset() is None:
        return ""
    return " at " + format_clock(to_local(ledger.session_start, t, ledger.timezone))


def role_phrase(ledger: VisitLedger, event: Event) -> str | None:
    """The check-7 role phrase the ledger backs for this event's subject, capitalised."""
    by_id, by_track = subject_index(ledger)
    role, basis = role_and_basis(event, by_id, by_track)
    for rp in ROLE_PHRASES:
        if rp.role != role:
            continue
        if rp.basis_prefixes and not (basis and basis.startswith(rp.basis_prefixes)):
            continue
        return rp.phrase[:1].upper() + rp.phrase[1:]
    return None


def _subject_key(ledger: VisitLedger, event: Event) -> str | None:
    by_id, by_track = subject_index(ledger)
    s = by_id.get(event.subject_id or "") or by_track.get(event.track_id)
    return s.id if s is not None else event.subject_id


AT_START_S = 0.5
"""An enter event this close to second 0 of the recording was already in view, not arriving."""


def _track_class(track_id: str) -> str | None:
    """SAM's class from the track id contract ``{camera}-{cls}-{n}`` (perception/tracks.py)."""
    parts = track_id.rsplit("-", 2)
    return parts[1] if len(parts) == 3 and parts[2].isdigit() else None


def template_story(
    ledger: VisitLedger, *, max_sentences: int = MAX_SENTENCES
) -> list[StorySentence]:
    all_events = _visit_events(ledger)
    labels = {p.id: p.label for p in ledger.protected_objects}
    # Leaving a zone is not leaving the view: only a track's last event can say that.
    last_t: dict[str, float] = {}
    first_t: dict[str, float] = {}
    for ev in all_events:
        last_t[ev.track_id] = max(last_t.get(ev.track_id, ev.t1), ev.t1)
        first_t[ev.track_id] = min(first_t.get(ev.track_id, ev.t0), ev.t0)

    def is_vehicle(track_id: str) -> bool:
        # Spark's note when there is one, else SAM's class: an undescribed car is still a car.
        note = ledger.appearance.get(track_id)
        return (note.class_ == "vehicle") if note is not None else _track_class(track_id) == "car"

    vehicles = {e.track_id for e in all_events if is_vehicle(e.track_id)}
    # Vehicles already in view when the recording started are one sentence, not one each;
    # their zone flicker is noise, and an exit at the end of the clip is the clip ending.
    parked = sorted(t for t in vehicles if first_t[t] < AT_START_S)
    end_t = max((e.t1 for e in all_events), default=0.0)
    parked_starts = [e for e in all_events if e.track_id in parked and e.t0 < AT_START_S]
    rest_events = [
        e
        for e in all_events
        if e.track_id not in parked
        or (e.type == "exit" and e.t1 >= last_t[e.track_id] and e.t1 < end_t - 1.0)
    ]
    out: list[StorySentence] = []
    if parked_starts:
        at = _clock(ledger, parked_starts[0].t0)
        if len(parked) == 1:
            target = humanise_id(parked_starts[0].target or "")
            where = f"in the {target} area" if target else "in view"
            text = f"A vehicle was already {where} when the recording started{at}."
        else:
            text = f"{len(parked)} vehicles were already in view when the recording started{at}."
        ids = list(dict.fromkeys(e.id for e in parked_starts))
        out.append(StorySentence(text=text, event_ids=ids, source="template"))
    events = _select(rest_events, max_sentences - len(out), vehicles)
    seen_tracks: set[str] = set(parked)
    prev_subject: str | None = None
    prev_vehicle = bool(out)
    for e in events:
        cam = ledger.camera_names.get(e.camera_id, e.camera_id)
        at = _clock(ledger, e.t0)
        vehicle = e.track_id in vehicles
        first = e.track_id not in seen_tracks
        seen_tracks.add(e.track_id)
        if vehicle:
            subj = "A vehicle" if first else "The vehicle"
        else:
            key = _subject_key(ledger, e)
            # After a sentence about a vehicle, "They" would read as the vehicle.
            if not out or prev_vehicle or (key is not None and key != prev_subject):
                subj = role_phrase(ledger, e) or "A person"
            else:
                subj = "They"
            prev_subject = key
        prev_vehicle = vehicle
        target = labels.get(e.target or "") or humanise_id(e.target or "")
        match e.type:
            case "enter" if first and e.t0 < AT_START_S:  # a person in view from the start
                where = f"in the {target} area" if target else "in view"
                text = f"{subj} was already {where} when the recording started{at}."
            case "enter":
                where = f"entered the {target} area" if target else "came into view"
                text = f"{subj} {where} on the {cam} camera{at}."
            case "exit":
                if target and e.t1 < last_t[e.track_id]:
                    text = f"{subj} left the {target} area on the {cam} camera{at}."
                else:
                    text = f"{subj} left the {cam} camera's view{at}."
            case "cross":
                what = f"the {target} line" if target else "a marked line"
                text = f"{subj} crossed {what} on the {cam} camera{at}."
            case "touch":
                what = f"the {target}" if target else "a protected object"
                text = f"{subj} touched {what} on the {cam} camera{at}."
            case "removed":
                what = labels.get(e.target or "", "object")
                text = (
                    f"The watched {what} was taken away while a person was next to it "
                    f"on the {cam} camera{at}."
                )
            case "dwell":
                secs = max(1, round(e.t1 - e.t0))
                near = f"near the {target}" if target else "in one place"
                text = f"{subj} stayed {near} for {secs} s on the {cam} camera{at}."
            case _:  # pragma: no cover - EventType is closed
                text = f"{subj} was seen on the {cam} camera{at}."
        out.append(StorySentence(text=text, event_ids=[e.id], source="template"))
    return out
