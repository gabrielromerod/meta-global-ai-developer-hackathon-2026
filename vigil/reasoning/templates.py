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


def _select(events: list[Event], limit: int) -> list[Event]:
    """Keep the first and last events, then the most important ones, in time order."""
    if len(events) <= limit:
        return events
    keep = {events[0].id, events[-1].id}
    rest = sorted(events[1:-1], key=lambda e: (_PRIORITY.get(e.type, 9), e.t0, e.id))
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


def template_story(
    ledger: VisitLedger, *, max_sentences: int = MAX_SENTENCES
) -> list[StorySentence]:
    all_events = _visit_events(ledger)
    events = _select(all_events, max_sentences)
    labels = {p.id: p.label for p in ledger.protected_objects}
    # Leaving a zone is not leaving the view: only a track's last event can say that.
    last_t: dict[str, float] = {}
    for ev in all_events:
        last_t[ev.track_id] = max(last_t.get(ev.track_id, ev.t1), ev.t1)
    out: list[StorySentence] = []
    seen_tracks: set[str] = set()
    prev_subject: str | None = None
    for e in events:
        cam = ledger.camera_names.get(e.camera_id, e.camera_id)
        at = _clock(ledger, e.t0)
        note = ledger.appearance.get(e.track_id)
        vehicle = note is not None and note.class_ == "vehicle"
        first = e.track_id not in seen_tracks
        seen_tracks.add(e.track_id)
        if vehicle:
            subj = "A vehicle" if first else "The vehicle"
        else:
            key = _subject_key(ledger, e)
            if not out or (key is not None and key != prev_subject):
                subj = role_phrase(ledger, e) or "A person"
            else:
                subj = "They"
            prev_subject = key
        target = labels.get(e.target or "") or humanise_id(e.target or "")
        match e.type:
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
