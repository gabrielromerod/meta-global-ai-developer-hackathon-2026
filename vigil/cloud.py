"""Production cloud adapters. Tests inject MetaClient with respx; no alternate HTTP path."""

from datetime import datetime
from pathlib import Path
from typing import Any

from vigil.meta.budget import SAM, SPARK, WONDER, estimate, preflight
from vigil.models import Config, Track, Watch, Window


def cloud_estimates(windows: list[Window]) -> list:
    """Conservative upper planning allowance: splits, six phrases, retries, story retry.

    The per-call guard remains authoritative as watches and visits are discovered.
    These are planning estimates, not measured costs.
    """
    estimates = []
    for w in windows:
        if w.status == "idle":
            continue
        frames = max(50, round((w.t1 - w.t0) * w.fps))
        estimates += [estimate(SAM, "perception_demo", frames=frames)] * (6 * 7 * 3)
        estimates += [estimate(SPARK, "appearance", in_tokens=32000, out_tokens=3000)] * 3
        estimates += [estimate(SPARK, "triage", in_tokens=4000, out_tokens=200)] * (16 * 3)
        estimates += [estimate(WONDER, "story", in_tokens=8000, out_tokens=1500)] * (16 * 2 * 3)
    return estimates


def run_cloud(
    *,
    client: Any,
    windows: list[Window],
    cfg: Config,
    session: str,
    session_start: datetime,
    result_dir: Path,
    rules: list,
    protected: list,
    watches: list,
    expected: list,
    checkins: list,
    confirm: bool,
    report=None,
    calibrations=None,
    ground=None,
    replay_bindings=None,
    camera_ai_events=None,
    camera_ai_events_measured: bool = False,
    truncated_after=None,
) -> dict:
    from vigil.ingest.media import probe
    from vigil.ingest.privacy import mask_clip
    from vigil.ingest.windows import cut_window
    from vigil.meta import sam, spark, wonder
    from vigil.perception.events import CARRIED_OBJECTS
    from vigil.perception.tagged import burn_tags
    from vigil.perception.zoom import cut_crop, map_back, plan_crops, shift_polygons
    from vigil.pipeline import phrases_for, run_scenario, upload_window

    estimates = cloud_estimates(windows)
    summary = preflight(estimates, confirm=True)
    if report:
        report(
            "Conservative pre-flight (planning estimate, not measured spend):\n"
            + "\n".join(summary.lines())
        )
    preflight(estimates, confirm=confirm)
    result_dir.mkdir(parents=True, exist_ok=True)
    appearance = {}
    appearance_calls = {}
    ledger_start = len(client.ledger)
    sam_cache = {}
    zoom_windows = {}
    notes_done = set()
    processed = []
    accepted = {}
    rejected = {}

    def zoomed(w: Window, phrase: str):
        """Carried objects are asked on crops around people (no person, no call)."""
        cam = cfg.camera(w.camera_id)
        info = probe(w.path)
        size, ref = (info.width, info.height), (cam.width, cam.height)
        people = sam_cache.get((w.id, "person"), [])
        found = []
        for i, plan in enumerate(plan_crops(people, *size, t0=w.t0, t1=w.t1)):
            crop = zoom_windows.get((w.id, i))
            polygons = shift_polygons(cam.privacy, plan, ref, size)
            if crop is None:
                raw = result_dir / "zoom" / f"{w.id}_{i}_raw.mp4"
                path = result_dir / "zoom" / f"{w.id}_{i}.mp4"
                cut_crop(w.path, raw, plan, w.t0)
                mask_clip(raw, path, polygons, ref_size=(plan.out_w, plan.out_h))
                raw.unlink()
                crop = Window(
                    id=f"{w.id}_zoom{i}",
                    camera_id=w.camera_id,
                    t0=plan.t0,
                    t1=plan.t1,
                    path=str(path),
                    fps=w.fps,
                    width=plan.out_w,
                    height=plan.out_h,
                )
                zoom_windows[w.id, i] = crop
            objs = sam.track_concept(
                client,
                crop,
                phrase,
                polygons=polygons,
                ref_size=(plan.out_w, plan.out_h),
                decode_masks=False,
            )
            found += [
                map_back(
                    o,
                    plan,
                    window_id=w.id,
                    index=i,
                    frame_size=size,
                    fps=w.fps,
                    window_t0=w.t0,
                )
                for o in objs
            ]
        return found

    def source(w: Window, phrase: str):
        if phrase in CARRIED_OBJECTS:
            return zoomed(w, phrase)
        cam = cfg.camera(w.camera_id)
        upload_window(client, w, cam)

        def cut(parent, t0, t1):
            dst = result_dir / "splits" / f"{parent.id}_{t0:.3f}_{t1:.3f}.mp4"
            cut_window(
                parent.path,
                dst,
                t0 - parent.t0,
                t1 - parent.t0,
                polygons=cam.privacy,
                ref_size=(cam.width, cam.height),
                max_width=1920 if cam.frame_layout == "duo_panorama" else 1280,
            )
            return dst

        return sam.track_concept(
            client, w, phrase, cut=cut, polygons=cam.privacy, ref_size=(cam.width, cam.height)
        )

    def notes(tracks: list[Track]):
        for w in processed:
            mine = [
                t
                for t in tracks
                if w.id in t.window_ids
                or (t.camera_id == w.camera_id and t.t_first < w.t1 and t.t_last >= w.t0)
            ]
            if w.status == "idle" or not mine:
                continue
            key = (w.id, tuple((t.id, t.tag) for t in mine))
            if key in notes_done:
                continue
            cam = cfg.camera(w.camera_id)
            clip = burn_tags(w, mine, cam, result_dir / "tagged" / f"{w.id}.mp4")
            found = spark.appearance_notes(
                client,
                clip,
                [t.tag for t in mine if t.tag],
                polygons=cam.privacy,
                ref_size=(cam.width, cam.height),
            )
            by_tag = {t.tag: t.id for t in mine}
            appearance.update(
                {by_tag[tag]: a.model_dump(by_alias=True) for tag, a in found.items()}
            )
            call = next(
                c for c in reversed(client.ledger.rows()) if c.purpose == "appearance_notes"
            )
            appearance_calls.update({by_tag[tag]: call.id for tag in found})
            notes_done.add(key)
        return appearance

    # Only the current window may generate fresh perception. Rebuilding the accumulated
    # evidence stitches across windows without sending a new watch into earlier footage.
    for current in sorted(windows, key=lambda w: (w.t0, w.camera_id, w.id)):
        active_watches = [*watches, *(Watch.model_validate(w) for w in accepted.values())]
        if current.status != "idle":
            for phrase in phrases_for(current, active_watches, session_start):
                sam_cache[current.id, phrase] = source(current, phrase)
        processed.append(current)
        result = run_scenario(
            {
                "scenario": session,
                "windows": processed,
                "camera_ai_events": camera_ai_events or [],
                "camera_ai_events_measured": camera_ai_events_measured,
                "truncated_after": truncated_after or {},
            },
            cfg=cfg,
            rules=rules,
            protected=protected,
            watches=active_watches,
            session_start=session_start,
            sam=lambda w, phrase: sam_cache.get((w.id, phrase), []),
            notes=notes,
            triage_model=lambda summary: spark.triage(client, summary),
            writer=lambda ledger, failures: wonder.write_story(client, ledger, failures),
            expected_windows=expected,
            checkins=checkins,
            calibrations=calibrations,
            ground=ground,
            replay_bindings=replay_bindings,
        )
        accepted.update({w["id"]: w for w in result["watches"]["accepted"]})
        rejected.update({w["id"]: w for w in result["watches"]["rejected"]})
    result["watches"]["accepted"] = list(accepted.values())
    result["watches"]["rejected"] = [w for wid, w in rejected.items() if wid not in accepted]
    for visit in result["visits"]:
        visit["watches"]["accepted"] = [
            w for w in accepted.values() if w["source_visit_id"] == visit["id"]
        ]
    result["appearance"] = appearance
    result["appearance_calls"] = appearance_calls
    result["cost_estimate"] = summary.model_dump()
    result["model_calls"] = [c.model_dump(mode="json") for c in client.ledger.rows()[ledger_start:]]
    return result
