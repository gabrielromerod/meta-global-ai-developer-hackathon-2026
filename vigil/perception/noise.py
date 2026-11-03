"""Keep outer-ring observations as counts, never visits or escalation evidence."""

from shapely.geometry import Point, Polygon

from vigil.models import Config, Event, Track


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
