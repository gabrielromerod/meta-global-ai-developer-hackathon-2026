"""Keep outer-ring observations as counts, never visits or escalation evidence."""

from shapely.geometry import Point, Polygon

from vigil.models import CameraAiEvent, Config, Event, Track


def property_evidence(
    tracks: list[Track], events: list[Event], cfg: Config
) -> tuple[list[Track], list[Event], dict[str, int]]:
    kept = []
    street = 0
    unplaced = 0
    starts = {}
    for track in tracks:
        camera = cfg.camera(track.camera_id)
        if not camera.zone_rings:
            kept.append(track)
            starts[track.id] = track.t_first
            continue
        property_frames = []
        saw_outer = False
        for frame in track.frames:
            foot = Point((frame.box.x1 + frame.box.x2) / 2, frame.box.y2)
            rings = {
                ring
                for zone, ring in camera.zone_rings.items()
                if Polygon(camera.zones[zone]).covers(foot)
            }
            saw_outer |= "outer" in rings
            if rings & {"middle", "inner"}:
                property_frames.append(frame)
        if not property_frames:
            street += int(saw_outer)
            unplaced += int(not saw_outer)
            continue
        start = property_frames[0].t
        frames = [f for f in track.frames if f.t >= start]
        kept.append(track.model_copy(update={"frames": frames, "t_first": start}))
        starts[track.id] = start
    retained_events = [
        event.model_copy(update={"t0": max(event.t0, starts[event.track_id])})
        for event in events
        if event.track_id in starts and event.t1 >= starts[event.track_id]
    ]
    return kept, retained_events, {"street_tracks": street, "unplaced_tracks": unplaced}


def prefilter_counts(
    ai_events: list[CameraAiEvent], tracks: list[Track], cfg: Config, observation, *, measured: bool
) -> dict | None:
    """Count distinct sensor events only when the observed interval can be classified."""
    if not measured:
        return None
    events = {event.id: event for event in ai_events}
    street = property_count = unknown = 0
    street_ids, property_ids, unknown_ids = [], [], []
    for event in events.values():
        camera = cfg.camera(event.camera_id)
        if event.kind == "doorbell_press" and camera.power_profile == "doorbell":
            property_count += 1
            property_ids.append(event.id)
            continue
        if (
            event.t1 is None
            or observation is None
            or not observation.covers(event.camera_id, event.t0, event.t1)
        ):
            unknown += 1
            unknown_ids.append(event.id)
            continue
        frames = [
            frame
            for track in tracks
            if track.camera_id == event.camera_id
            and track.cls == {"person": "person", "vehicle": "car"}.get(event.kind)
            for frame in track.frames
            if event.t0 <= frame.t <= event.t1
        ]
        rings = []
        for frame in frames:
            foot = Point((frame.box.x1 + frame.box.x2) / 2, frame.box.y2)
            seen = {
                ring
                for zone, ring in camera.zone_rings.items()
                if Polygon(camera.zones[zone]).covers(foot)
            }
            rings.append(seen)
        if any(r & {"middle", "inner"} for r in rings):
            property_count += 1
            property_ids.append(event.id)
        elif rings and all("outer" in r for r in rings):
            street += 1
            street_ids.append(event.id)
        else:
            unknown += 1
            unknown_ids.append(event.id)
    return {
        "camera_events": len(events),
        "on_property": property_count if not unknown else None,
        "street_events": street if not unknown else None,
        "unclassified_camera_events": unknown,
        "street_event_ids": street_ids,
        "property_event_ids": property_ids,
        "unclassified_event_ids": unknown_ids,
    }
