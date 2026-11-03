"""Production cloud adapters. Tests inject MetaClient with respx; no alternate HTTP path."""

from datetime import datetime
from pathlib import Path
from typing import Any

from vigil.meta.budget import SAM, SPARK, WONDER, estimate, preflight
from vigil.models import Config, Track, Window


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
) -> dict:
    from vigil.ingest.windows import cut_window
    from vigil.meta import sam, spark, wonder
    from vigil.perception.tagged import burn_tags
    from vigil.pipeline import run_scenario, upload_window

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

    def source(w: Window, phrase: str):
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
            )
            return dst

        return sam.track_concept(
            client, w, phrase, cut=cut, polygons=cam.privacy, ref_size=(cam.width, cam.height)
        )

    def notes(tracks: list[Track]):
        for w in windows:
            mine = [
                t
                for t in tracks
                if w.id in t.window_ids
                or (t.camera_id == w.camera_id and t.t_first < w.t1 and t.t_last >= w.t0)
            ]
            if w.status == "idle" or not mine:
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
        return appearance

    result = run_scenario(
        {"scenario": session, "windows": windows},
        cfg=cfg,
        rules=rules,
        protected=protected,
        watches=watches,
        session_start=session_start,
        sam=source,
        notes=notes,
        triage_model=lambda summary: spark.triage(client, summary),
        writer=lambda ledger, failures: wonder.write_story(client, ledger, failures),
        expected_windows=expected,
        checkins=checkins,
    )
    result["appearance"] = appearance
    result["appearance_calls"] = appearance_calls
    result["cost_estimate"] = summary.model_dump()
    result["model_calls"] = [c.model_dump(mode="json") for c in client.ledger.rows()[ledger_start:]]
    return result
