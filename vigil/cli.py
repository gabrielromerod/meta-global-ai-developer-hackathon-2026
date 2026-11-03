"""`vigil` command line (spec 9.2: typer), wired to the implemented modules.

Exit codes: 0 done; 1 bad input or a refused run (message on stderr, never a traceback);
2 ``blocked: <reason>`` when field hardware, an optional extra, measured data or credits
are needed (see docs/readiness.md).

Batch commands that can spend money print a pre-flight estimate first and need --confirm
above $5 (spec 11.6, safeguard 3); the budget guard lives in vigil/meta/budget.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, NoReturn
from zoneinfo import ZoneInfo

import typer

from vigil import __version__

app = typer.Typer(help="Vigil: one cited story per visit.", no_args_is_help=True)
spatial = typer.Typer(
    help="LiDAR model, calibration and coverage (FR-035 to FR-038).", no_args_is_help=True
)
reolink = typer.Typer(help="Reolink probe and capture (FR-030, FR-031).", no_args_is_help=True)
cost = typer.Typer(help="Budget estimates (FR-043, spec 11.4).", no_args_is_help=True)
demo = typer.Typer(help="Demo bundles (FR-027).", no_args_is_help=True)
app.add_typer(spatial, name="spatial")
app.add_typer(reolink, name="reolink")
app.add_typer(cost, name="cost")
app.add_typer(demo, name="demo")

CLIP_SUFFIXES = (".mp4", ".mkv", ".mov", ".ts", ".avi")
SCAN_SUFFIXES = (".ply", ".obj", ".glb", ".gltf", ".usdz", ".e57", ".las", ".pcd")
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

ConfigOpt = Annotated[
    Path | None, typer.Option("--config", help="cameras.yaml (default: VIGIL_CONFIG_PATH).")
]
DbOpt = Annotated[Path | None, typer.Option("--db", help="SQLite DB (default: VIGIL_DB_PATH).")]
EnvFileOpt = Annotated[
    Path, typer.Option("--env-file", help="Reads camera hosts and credentials from this file.")
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blocked(reason: object) -> NoReturn:
    text = str(reason).strip()
    text = text.removeprefix("blocked:").strip()
    typer.secho(f"blocked: {text}", fg="yellow", err=True)
    raise typer.Exit(code=2)


def _fail(msg: object) -> NoReturn:
    typer.secho(f"error: {msg}", fg="red", err=True)
    raise typer.Exit(code=1)


def _settings():
    from vigil.settings import get_settings

    return get_settings()


def _config_path(config: Path | None) -> Path:
    return Path(config) if config is not None else Path(_settings().config_path)


def _load_cfg(path: Path):
    from vigil.ingest.config import ConfigError, load_config

    try:
        return load_config(path)
    except ConfigError as err:
        _fail(f"config: {err}")


def _require_ffmpeg() -> None:
    import vigil.settings

    try:
        vigil.settings.ffmpeg_bin()
        vigil.settings.ffprobe_bin()
    except FileNotFoundError as err:
        _blocked(err)


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str, ensure_ascii=False)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(obj) + "\n", encoding="utf-8", newline="\n")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fail(f"file not found: {path}")
    except (OSError, json.JSONDecodeError) as err:
        _fail(f"cannot read {path}: {err}")


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print the Vigil version."""
    typer.echo(__version__)


# ---------------------------------------------------------------------------
# ingest (FR-001 to FR-005)
# ---------------------------------------------------------------------------


def _find_clips(clip_dir: Path, camera_ids: list[str]) -> tuple[dict[str, Path], list[str]]:
    """``camera_id -> clip``: ``<cam>.mp4``, ``<cam>_<anything>.mp4`` or ``<cam>/<clip>``."""
    found: dict[str, list[Path]] = {}
    skipped: list[str] = []
    by_len = sorted(camera_ids, key=len, reverse=True)
    for p in sorted(clip_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in CLIP_SUFFIXES:
            skipped.append(p.name)
            continue
        rel = p.relative_to(clip_dir)
        cam = None
        if len(rel.parts) > 1 and rel.parts[0] in camera_ids:
            cam = rel.parts[0]
        else:
            stem = p.stem
            cam = next((c for c in by_len if stem == c or stem.startswith(f"{c}_")), None)
        if cam is None:
            skipped.append(str(rel))
            continue
        found.setdefault(cam, []).append(p)
    multi = {c: ps for c, ps in found.items() if len(ps) > 1}
    if multi:
        names = "; ".join(f"{c}: {', '.join(p.name for p in ps)}" for c, ps in multi.items())
        _fail(f"one clip per camera per session; found several ({names})")
    clips = {c: found[c][0] for c in camera_ids if c in found}
    return clips, skipped


_CLIP_TIME_RE = re.compile(r"_(\d{8}T\d{6})Z$")


def _session_start(
    start: str | None, clips: dict[str, Path], offsets: dict[str, float], tz_name: str
) -> tuple[datetime, str]:
    """Wall-clock time of session time 0, timezone-aware in the config timezone."""
    tz = ZoneInfo(tz_name)
    if start is not None:
        try:
            dt = datetime.fromisoformat(start)
        except ValueError:
            _fail(f"--start must be ISO-8601, got {start!r}")
        return (dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)), "--start"
    for cam_id, clip in clips.items():
        m = _CLIP_TIME_RE.search(clip.stem)
        if m:
            t = datetime.strptime(m[1], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
            # clip time 0 is session time offsets[cam]; session 0 = clip start - offset
            return (t - timedelta(seconds=offsets[cam_id])).astimezone(tz), f"{clip.name}"
    ref = next(iter(clips))
    t = datetime.fromtimestamp(clips[ref].stat().st_mtime, tz=UTC)
    return (t - timedelta(seconds=offsets[ref])).astimezone(tz), "file time"


@app.command()
def ingest(
    clip_dir: Annotated[Path, typer.Argument(help="Folder with one clip per camera.")],
    session: Annotated[str, typer.Option(help="Session name (folder under --out).")] = "default",
    config: ConfigOpt = None,
    out: Annotated[
        Path | None, typer.Option(help="Windows root (default: <data_dir>/windows).")
    ] = None,
    sync: Annotated[
        bool, typer.Option("--sync/--no-sync", help="Measure offsets from the clap/flash.")
    ] = True,
    reference: Annotated[
        str | None, typer.Option(help="Reference camera for the sync (default: first found).")
    ] = None,
    start: Annotated[
        str | None,
        typer.Option(help="Session start (session time 0), ISO-8601; naive = config timezone."),
    ] = None,
) -> None:
    """Sync, mask, window and motion-gate raw clips (FR-001 to FR-005).

    Clips are matched to cameras by name: <camera_id>.mp4, <camera_id>_<anything>.mp4 or
    <camera_id>/<clip>.mp4, one per camera. Writes <out>/<session>/windows.json (the windows
    `vigil process` reads) and session.json (session_start, offsets, active windows; keys
    you add there, such as rules, are kept). Offsets measured from the clap/flash (FR-002)
    are printed and saved in session.json; they are NOT written back to cameras.yaml
    (rewriting the YAML would drop its comments). Copy them into offset_s by hand if you
    want them as defaults. --no-sync uses the configured offset_s values as they are.
    The session start comes from --start, else a capture timestamp in a clip name
    (<camera>_YYYYmmddTHHMMSSZ), else the reference clip's file time (warned).
    """
    if not _SESSION_RE.match(session):
        _fail(f"invalid session name {session!r}: letters, digits, '_', '.', '-' only")
    clip_dir = Path(clip_dir)
    if not clip_dir.is_dir():
        _fail(f"clip folder not found: {clip_dir}")
    cfg_path = _config_path(config)
    cfg = _load_cfg(cfg_path)
    clips, skipped = _find_clips(clip_dir, [c.id for c in cfg.cameras])
    if not clips:
        known = ", ".join(c.id for c in cfg.cameras)
        _fail(f"no clips for the configured cameras ({known}) in {clip_dir}")
    _require_ffmpeg()

    from vigil.ingest.config import ConfigError, privacy_polygons
    from vigil.ingest.media import MediaError
    from vigil.ingest.motion import gate_window, select_active
    from vigil.ingest.sync import SyncError, apply_offsets, sync_session
    from vigil.ingest.windows import WindowError, cut_windows

    # Fail before sync, directories, or derived media are written.
    privacy_dir = cfg_path.parent / "privacy"
    privacy_by_camera = {}
    try:
        for cam_id in clips:
            cam = cfg.camera(cam_id)
            polys = privacy_polygons(cfg, cam_id, privacy_dir=privacy_dir)
            if not polys and not cam.privacy_none_needed:
                _fail(f"camera {cam_id}: privacy polygons required, or set privacy: none_needed")
            privacy_by_camera[cam_id] = polys
    except ConfigError as err:
        _fail(f"privacy: {err}")

    meta: dict[str, Any] = {
        "session": session,
        "clip_dir": str(clip_dir),
        "config": str(cfg_path),
        "synced": False,
        "reference": None,
        "residual_s": None,
        "excluded": {},
        "skipped_files": skipped,
    }
    try:
        if sync:
            res = sync_session(clips, reference=reference)
            cfg = apply_offsets(cfg, res.offsets)
            meta.update(
                synced=True,
                reference=res.reference,
                residual_s=res.residual_s,
                excluded=res.excluded,
            )
    except SyncError as err:
        _fail(f"sync (FR-002): {err}; film the clap/flash, or pass --no-sync to use offset_s")
    except FileNotFoundError as err:
        _blocked(err)

    out_root = Path(out) if out is not None else Path(_settings().data_dir) / "windows"
    session_dir = out_root / session
    session_dir.mkdir(parents=True, exist_ok=True)
    privacy_dir = cfg_path.parent / "privacy"
    offsets = {c: cfg.camera(c).offset_s for c in clips}
    windows = []
    try:
        for cam_id, clip in clips.items():
            cam = cfg.camera(cam_id)
            polys = privacy_by_camera[cam_id]
            cut = cut_windows(
                clip,
                session_dir,
                cam_id,
                session_start_s=cam.offset_s,
                polygons=polys,
                ref_size=(cam.width, cam.height),
            )
            windows += [gate_window(w, cam, polygons=polys) for w in cut]
    except FileNotFoundError as err:
        _blocked(err)
    except (MediaError, WindowError, ConfigError, ValueError) as err:
        _fail(f"windowing: {err}")

    active = select_active(windows)
    session_start, start_source = _session_start(start, clips, offsets, cfg.timezone)
    meta["session_start"] = session_start.isoformat()
    meta["session_start_source"] = start_source
    meta["offsets"] = offsets
    meta["active"] = [w.id for w in active]
    meta_path = session_dir / "session.json"
    previous: dict[str, Any] = {}
    if meta_path.exists():
        old = _read_json(meta_path)
        previous = old if isinstance(old, dict) else {}
    _write_json(meta_path, {**previous, **meta})
    _write_json(session_dir / "windows.json", [w.model_dump(mode="json") for w in windows])

    typer.echo(f"session {session}: {len(clips)} cameras, reference {meta['reference'] or '-'}")
    typer.echo(f"session start: {meta['session_start']} (from {start_source})")
    if start_source == "file time":
        typer.secho(
            "warning: session start guessed from the clip's file time; pass --start",
            fg="yellow",
        )
    if meta["residual_s"] is not None:
        typer.echo(f"sync residual: {meta['residual_s']:.3f} s")
    for cam_id in clips:
        n = sum(1 for w in windows if w.camera_id == cam_id)
        a = sum(1 for w in active if w.camera_id == cam_id)
        note = (
            f"  (no sync event: {meta['excluded'][cam_id]})" if cam_id in meta["excluded"] else ""
        )
        typer.echo(f"  {cam_id}: offset {offsets[cam_id]:+.3f} s, {n} windows, {a} active{note}")
    typer.echo(f"{len(active)} of {len(windows)} windows active; written to {session_dir}")
    typer.echo("offsets saved in session.json only; cameras.yaml was not changed")
    if skipped:
        typer.echo(f"skipped (not a clip of a configured camera): {', '.join(skipped)}")


# ---------------------------------------------------------------------------
# process (perception and reasoning)
# ---------------------------------------------------------------------------


@app.command()
def process(
    session: Annotated[str, typer.Option(help="Session name from `vigil ingest`.")] = "default",
    confirm: Annotated[
        bool, typer.Option(help="Allow a batch whose estimate is above $5 (spec 11.6).")
    ] = False,
    cloud: Annotated[
        bool, typer.Option(help="Explicitly opt into cloud adapters (cache-only in sandbox).")
    ] = False,
) -> None:
    """Run perception and reasoning on a session (pre-flight estimate first)."""
    try:
        from vigil.pipeline import process_session
    except ImportError as err:
        _blocked(f"the pipeline (vigil.pipeline) is not available: {err}")

    from vigil.meta.budget import BudgetExceeded, ConfirmRequired

    try:
        if cloud:
            result = process_session(session, confirm=confirm, cloud=True, report=typer.echo)
        else:
            result = process_session(session, confirm=confirm)
    except ConfirmRequired as err:
        _fail(str(err))
    except BudgetExceeded as err:
        _blocked(f"{err} (credits)")
    except FileNotFoundError as err:
        _fail(f"{err}; run `vigil ingest` first")
    except Exception as err:
        if _is_blocking(err):
            msg = str(err)
            _blocked(msg if msg.startswith("blocked:") else f"{type(err).__name__}: {msg}")
        raise
    typer.echo(_dump(result))


def _is_blocking(err: Exception) -> bool:
    """Errors that mean credits, keys, recordings or a backend are missing, not a bug.

    The pipeline signals missing inputs as ``RuntimeError("blocked: ...")``.
    """
    from vigil.meta.client import CacheMiss, MetaAuthError, MetaUnavailable
    from vigil.meta.glimmer import GlimmerUnavailable

    if isinstance(err, RuntimeError) and str(err).startswith("blocked:"):
        return True
    return isinstance(err, MetaAuthError | MetaUnavailable | GlimmerUnavailable | CacheMiss)


# ---------------------------------------------------------------------------
# eval (FR-024, NFR-023, NFR-025/026, latency)
# ---------------------------------------------------------------------------


@app.command(name="eval")
def eval_(
    labels: Annotated[Path, typer.Option(help="Pre-registered labels.")] = Path("eval/labels"),
    results: Annotated[Path, typer.Option(help="Pipeline results (folder or JSON).")] = Path(
        "eval/outputs"
    ),
    out: Annotated[Path, typer.Option(help="Metrics JSON.")] = Path("eval/results.json"),
    table: Annotated[bool, typer.Option(help="Print the EVAL.md table.")] = False,
    spatial_: Annotated[
        bool, typer.Option("--spatial", help="Marker-walk accuracy only (NFR-025/026).")
    ] = False,
    spatial_dir: Annotated[Path, typer.Option(help="Marker-walk JSON.")] = Path("eval/spatial"),
    spatial_out: Annotated[Path, typer.Option(help="Spatial report.")] = Path(
        "eval/spatial_results.json"
    ),
    latency: Annotated[
        bool, typer.Option(help="Model-call latency p50/p90 from the ledger only.")
    ] = False,
    db_path: DbOpt = None,
    latency_out: Annotated[Path, typer.Option(help="Latency report.")] = Path(
        "eval/latency_results.json"
    ),
) -> None:
    """Compute EVAL metrics against pre-registered labels (FR-024).

    Reads results only (no model calls). --spatial and --latency run just those reports.
    """
    if spatial_ or latency:
        if spatial_:
            _eval_spatial(spatial_dir, spatial_out)
        if latency:
            _eval_latency(db_path, latency_out)
        return

    from vigil.eval.run import render_markdown, run_eval

    try:
        metrics = run_eval(labels, out, results=results)
    except FileNotFoundError as err:
        _fail(err)
    except (ValueError, KeyError) as err:
        _fail(f"labels or results are malformed: {err}")
    t = metrics.get("totals", {})
    typer.echo(
        f"wrote {out}: {t.get('scenarios', 0)} scenarios, "
        f"{t.get('correct_verdicts', 0)} correct verdicts"
    )
    if table:
        typer.echo(render_markdown(metrics))


def _eval_spatial(spatial_dir: Path, spatial_out: Path) -> None:
    from vigil.eval.spatial_eval import spatial_report

    files = (
        sorted(p for p in Path(spatial_dir).glob("*.json") if not p.name.startswith("_"))
        if Path(spatial_dir).is_dir()
        else []
    )
    if not files:
        _blocked(f"no marker-walk recordings in {spatial_dir} (T-15, field hardware)")
    points: list[dict] = []
    for f in files:
        data = _read_json(f)
        pts = data.get("points", []) if isinstance(data, dict) else data
        if not isinstance(pts, list):
            _fail(f"{f}: expected a list of points or {{'points': [...]}}")
        points += pts
    try:
        report = spatial_report(points)
    except (KeyError, TypeError, ValueError) as err:
        _fail(f"marker-walk points are malformed: {err}")
    _write_json(spatial_out, report)
    typer.echo(_dump(report))


def _percentile(values: list[float], q: float) -> float:
    import numpy as np

    return round(float(np.percentile(np.asarray(values, float), q)), 1)


def _eval_latency(db_path: Path | None, latency_out: Path) -> None:
    from vigil.store import db

    path = Path(db_path) if db_path is not None else Path(_settings().db_path)
    if not path.exists():
        _blocked(f"no ledger at {path}: latency needs measured live calls (credits)")
    conn = db.connect(path)
    try:
        calls = db.model_calls(conn)
    finally:
        conn.close()
    by_purpose: dict[str, list[float]] = {}
    for c in calls:
        if c.latency_ms is not None and not c.cached and c.ok:
            by_purpose.setdefault(c.purpose, []).append(float(c.latency_ms))
    if not by_purpose:
        _blocked("no live (uncached) model calls with latency in the ledger (credits)")
    report = {
        purpose: {
            "n": len(v),
            "p50_ms": _percentile(v, 50),
            "p90_ms": _percentile(v, 90),
            "max_ms": max(v),
        }
        for purpose, v in sorted(by_purpose.items())
    }
    _write_json(latency_out, report)
    typer.echo(_dump(report))


# ---------------------------------------------------------------------------
# export and demo (FR-027)
# ---------------------------------------------------------------------------


@app.command()
def export(
    out: Annotated[Path, typer.Option(help="Bundle folder.")] = Path("demo"),
    db_path: DbOpt = None,
    config: ConfigOpt = None,
    session: Annotated[
        str | None, typer.Option(help="Export a processed session with its masked video.")
    ] = None,
) -> None:
    """Write the demo bundle from a processed DB (FR-027). Run the privacy gate before
    committing anything it writes."""
    from vigil.store.export import export_bundle

    if session is not None:
        from vigil.store.export import export_session

        try:
            path = export_session(session, out, settings=_settings())
        except (FileNotFoundError, ValueError) as err:
            _fail(str(err))
        typer.echo(f"exported masked session to {path}")
        return

    try:
        bundle = export_bundle(out, db_path, config=config)
    except FileNotFoundError as err:
        _fail(err)
    except (ValueError, OSError) as err:
        _fail(f"export: {err}")
    typer.echo(f"bundle written to {bundle}")
    typer.echo(
        "privacy gate: run `uv run python scripts/privacy_scan.py` and "
        "`bash scripts/metadata_scan.sh demo` before committing it"
    )


@demo.command("synthetic")
def demo_synthetic(
    out: Annotated[Path | None, typer.Option(help="Default: demo/synthetic.")] = None,
) -> None:
    """Rebuild the SYNTHETIC demo bundle (invented scenes; no footage)."""
    import importlib.util

    from vigil.settings import REPO_ROOT

    script = REPO_ROOT / "demo" / "synthetic" / "build.py"
    if not script.exists():
        _fail(f"synthetic builder not found: {script}")
    spec = importlib.util.spec_from_file_location("vigil_demo_synthetic_build", script)
    if spec is None or spec.loader is None:
        _fail(f"cannot load {script}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    path = mod.build(out)
    typer.echo(f"synthetic bundle written to {path}")


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the web app and API (sandbox or LAN)."""
    import uvicorn

    uvicorn.run("vigil.api.app:create_app", host=host, port=port, factory=True)


# ---------------------------------------------------------------------------
# reolink (FR-030, FR-031)
# ---------------------------------------------------------------------------


def _load_env(env_file: Path) -> None:
    if Path(env_file).is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)


def _hosted_cameras(cfg) -> list:
    cams = [
        c
        for c in cfg.cameras
        if c.source and c.source.host_env and os.environ.get(c.source.host_env, "").strip()
    ]
    if not cams:
        _blocked(
            "no camera hosts configured: set source.host_env in cameras.yaml and those "
            "variables in .env (field hardware, T-04)"
        )
    return cams


@reolink.command("probe")
def reolink_probe(
    config: ConfigOpt = None,
    env_file: EnvFileOpt = Path(".env"),
    camera: Annotated[str | None, typer.Option(help="Only this camera ID.")] = None,
) -> None:
    """Probe every configured camera (FR-030). Prints one redacted JSON report per camera."""
    _load_env(env_file)
    cfg = _load_cfg(_config_path(config))
    if camera is not None:
        if camera not in {c.id for c in cfg.cameras}:
            _fail(f"unknown camera {camera!r}")
        cfg = cfg.model_copy(update={"cameras": [cfg.camera(camera)]})
    _hosted_cameras(cfg)
    from vigil.reolink import probe as rp

    try:
        reports = asyncio.run(rp.probe_all(cfg.cameras))
    except rp.ReolinkUnavailable as err:
        _blocked(err)
    for rep in reports:
        typer.echo(rp.redact(rep.model_dump_json()))
    failed = [r.camera_id for r in reports if not r.ok]
    if failed:
        typer.secho(f"probe failed for: {', '.join(failed)}", fg="red", err=True)
        raise typer.Exit(code=1)


@reolink.command("capture")
def reolink_capture(
    out_dir: Annotated[Path, typer.Option(help="Segment ring folder.")] = Path("data/segments"),
    config: ConfigOpt = None,
    env_file: EnvFileOpt = Path(".env"),
    direct: Annotated[
        bool, typer.Option(help="Read standalone Wi-Fi cameras directly (default).")
    ] = True,
    camera: Annotated[str | None, typer.Option(help="Only this camera ID.")] = None,
    max_restarts: Annotated[int | None, typer.Option(help="Stop after N restarts.")] = None,
) -> None:
    """Capture for a filming session until Ctrl+C. Direct Wi-Fi RTSP; battery cameras refused."""
    _load_env(env_file)
    cfg = _load_cfg(_config_path(config))
    if camera is not None:
        if camera not in {c.id for c in cfg.cameras}:
            _fail(f"unknown camera {camera!r}")
        cfg = cfg.model_copy(update={"cameras": [cfg.camera(camera)]})
    cams = _hosted_cameras(cfg)
    _require_ffmpeg()
    from vigil.reolink import capture as rc
    from vigil.reolink.probe import CredentialsError, ReolinkUnavailable

    try:
        sups = asyncio.run(
            rc.run_capture(
                cams, Path(out_dir), via_restreamer=not direct, max_restarts=max_restarts
            )
        )
    except KeyboardInterrupt:
        typer.echo("capture stopped")
        return
    except (CredentialsError, ReolinkUnavailable) as err:
        _blocked(err)
    except ValueError as err:
        _fail(str(err))
    for s in sups or []:
        outages = getattr(s, "outages", [])
        typer.echo(f"{s.camera_id}: {len(outages)} outages")


# ---------------------------------------------------------------------------
# spatial (FR-035 to FR-038)
# ---------------------------------------------------------------------------


@spatial.command("import-glb")
def spatial_import_glb(
    source: Annotated[Path, typer.Argument(help="Uncompressed GLB below 15 MB.")],
    frame: Annotated[
        Path, typer.Option(help="JSON: origin, x_point and up_point in scan coordinates.")
    ],
    out: Annotated[Path, typer.Option(help="Imported spatial model and twin metadata.")] = Path(
        "data/spatial"
    ),
) -> None:
    """Import a static GLB into the house frame for locate, coverage and the viewer."""
    from vigil.spatial.glb import import_glb
    from vigil.spatial.scan import world_frame

    points = _read_json(frame)
    try:
        transform = world_frame(points["origin"], points["x_point"], points["up_point"])
        model = import_glb(source, out, frame=transform)
    except (ValueError, KeyError, OSError) as err:
        _fail(str(err))
    typer.echo(f"imported {model}; field acceptance remains Not verified")


@spatial.command("build")
def spatial_build(
    segments: Annotated[
        list[Path] | None, typer.Argument(help="Scan segment files or folders.")
    ] = None,
    distances: Annotated[
        Path | None, typer.Option(help="JSON list of tape-measured distances (scale check).")
    ] = None,
) -> None:
    """Build the house model from LiDAR segments (FR-035)."""
    from vigil.spatial.scan import Distance, SpatialBuildBlockedError, build_model

    files: list[Path] = []
    for p in segments or []:
        if Path(p).is_dir():
            files += sorted(q for q in Path(p).iterdir() if q.suffix.lower() in SCAN_SUFFIXES)
        else:
            files.append(Path(p))
    measured = []
    if distances is not None:
        raw = _read_json(distances)
        try:
            measured = [Distance.model_validate(d) for d in raw]
        except (TypeError, ValueError) as err:
            _fail(f"{distances}: {err}")
    try:
        result = build_model(files, measured)
    except SpatialBuildBlockedError as err:
        _blocked(err)
    except ValueError as err:
        _fail(err)
    typer.echo(f"model built: {result}")


def _load_pairs(path: Path, key: str = "pairs", model: Any = None) -> list:
    from vigil.spatial.calibrate import MarkerPair

    model = model or MarkerPair
    raw = _read_json(path)
    items = raw.get(key, []) if isinstance(raw, dict) else raw
    try:
        return [model.model_validate(p) for p in items]
    except (TypeError, ValueError) as err:
        _fail(f"{path}: marker pairs are malformed: {err}")


@spatial.command("calibrate")
def spatial_calibrate(
    camera: Annotated[str, typer.Argument(help="Camera id from cameras.yaml.")],
    frames: Annotated[
        Path | None, typer.Option(help="Checkerboard views (*.png, *.jpg) for intrinsics.")
    ] = None,
    pairs: Annotated[
        Path | None,
        typer.Option(help="Landmark pairs JSON (6 accepted landmarks) from the LAN tool."),
    ] = None,
    audit: Annotated[
        Path | None,
        typer.Option(help="Surveyed audit markers JSON (benchmark only, never solved on)."),
    ] = None,
    fisheye: Annotated[bool, typer.Option(help="Fisheye lens model.")] = False,
    pattern: Annotated[str, typer.Option(help="Inner corners, columns x rows.")] = "9x6",
    square_m: Annotated[float, typer.Option(help="Checkerboard square size (m).")] = 0.025,
    hfov: Annotated[
        float | None,
        typer.Option(help="Nominal horizontal FOV (default: the camera's hfov_deg, else 90)."),
    ] = None,
    method: Annotated[str, typer.Option(help="pnp_ransac or homography.")] = "pnp_ransac",
    config: ConfigOpt = None,
    out: Annotated[
        Path | None, typer.Option(help="calibration.json (default: next to cameras.yaml).")
    ] = None,
) -> None:
    """Calibrate one camera into the model (FR-036, FR-037) and write the report (NFR-024).

    Intrinsics: nominal FOV from the datasheet (--hfov, else the camera's ``hfov_deg``),
    the primary path; or a lens profile from checkerboard --frames (RMS under 1 px).
    Extrinsics from --pairs: PnP with RANSAC on every landmark (6 in the product path, none
    held out). Accuracy is measured only by --audit: surveyed markers that never enter the
    solve; their mean ground error is stored and used by locate() for r95.
    """
    from vigil.models import Calibration
    from vigil.spatial.calibrate import (
        DEFAULT_HFOV_DEG,
        SurveyedMarker,
        audit_error,
        calibrate_extrinsics,
        calibrate_intrinsics,
        calibration_report,
        intrinsics_from_fov,
        load_calibrations,
        save_calibrations,
        with_audit,
    )

    cfg_path = _config_path(config)
    cfg = _load_cfg(cfg_path)
    try:
        cam = cfg.camera(camera)
    except KeyError:
        _fail(f"unknown camera {camera!r} (known: {', '.join(c.id for c in cfg.cameras)})")
    if method not in ("pnp_ransac", "homography"):
        _fail("--method must be pnp_ransac or homography")
    if pairs is None:
        _blocked(
            "extrinsics need marker pairs (--pairs) clicked in web/calibrate on the LAN "
            "(field hardware, T-14)"
        )
    try:
        cols, rows = (int(v) for v in pattern.lower().split("x"))
    except ValueError:
        _fail(f"--pattern must look like 9x6, got {pattern!r}")
    marker_pairs = _load_pairs(pairs)
    markers = _load_pairs(audit, "markers", SurveyedMarker) if audit is not None else []
    hfov_deg = hfov if hfov is not None else (cam.hfov_deg or DEFAULT_HFOV_DEG)
    if not 0.0 < hfov_deg < 180.0:
        _fail(f"--hfov must be in (0, 180) degrees, got {hfov_deg}")

    size = (cam.width, cam.height)
    if frames is not None:
        if not Path(frames).is_dir():
            _fail(f"frames folder not found: {frames}")
        views = sorted(
            p for p in Path(frames).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")
        )
        k = calibrate_intrinsics(
            views, fisheye, pattern=(cols, rows), square_m=square_m, hfov_deg=hfov_deg,
            image_size=size,
        )  # fmt: skip
    else:
        k = intrinsics_from_fov(hfov_deg, size[0], size[1])
    try:
        ext = calibrate_extrinsics(marker_pairs, k, method=method, holdout=0)
    except ValueError as err:
        _fail(f"extrinsics: {err}")
    cal = Calibration(camera_id=camera, intrinsics=k, extrinsics=ext, date=date.today().isoformat())
    if markers:
        try:
            report = audit_error(cal, markers, landmarks=marker_pairs)
        except ValueError as err:
            _fail(f"audit: {err}")
        cal = with_audit(cal, report)

    out_path = Path(out) if out is not None else cfg_path.parent / "calibration.json"
    existing = []
    if out_path.exists():
        try:
            existing = load_calibrations(out_path)
        except (ValueError, json.JSONDecodeError) as err:
            _fail(f"{out_path}: {err}")
    merged = [c for c in existing if c.camera_id != camera] + [cal]
    merged.sort(key=lambda c: c.camera_id)
    save_calibrations(out_path, merged)
    reports = [calibration_report(c) for c in merged]
    report_path = out_path.with_name("calibration_report.json")
    _write_json(report_path, {"cameras": reports})
    typer.echo(_dump(calibration_report(cal)))
    typer.echo(f"wrote {out_path} and {report_path}")


def _scene_from_site_plan(data: dict):
    """A RaycastScene from a measured site plan (spec 7 fallback level 3) or a twin.json:
    ``{"ground": {"min": [x, z], "max": [x, z]}, "site_plan": {"boxes": [...]}}`` where a
    box is ``{"name", "min": [x, z], "max": [x, z], "h"}`` (``boxes`` may be top level)."""
    from vigil.spatial.geometry import Occluder, RaycastScene, box_mesh, plane_ground

    ground = data["ground"]
    boxes = (data.get("site_plan") or {}).get("boxes", data.get("boxes", []))
    g = plane_ground(ground["min"][0], ground["min"][1], ground["max"][0], ground["max"][1])
    occ = [
        Occluder(
            str(b.get("name") or b.get("id") or "occluder").lower(),
            box_mesh((b["min"][0], 0.0, b["min"][1]), (b["max"][0], float(b["h"]), b["max"][1])),
        )
        for b in boxes
    ]
    return RaycastScene(ground=g, occluders=occ)


@spatial.command("coverage")
def spatial_coverage(
    config: ConfigOpt = None,
    calibration: Annotated[
        Path | None, typer.Option(help="calibration.json (default: next to cameras.yaml).")
    ] = None,
    site_plan: Annotated[
        Path | None, typer.Option(help="Site plan or twin JSON (ground and occluder boxes).")
    ] = None,
    cell_m: Annotated[float, typer.Option(help="Grid cell (m).")] = 0.25,
    max_range_m: Annotated[float | None, typer.Option(help="Ignore cells beyond this.")] = None,
    write: Annotated[
        bool, typer.Option("--write/--dry-run", help="Update blind_regions in cameras.yaml.")
    ] = False,
    replace_all: Annotated[bool, typer.Option(help="Replace every blind region.")] = False,
    grid_out: Annotated[
        Path | None, typer.Option(help="Write the coverage grid JSON (3D viewer layer).")
    ] = None,
) -> None:
    """Compute coverage and blind regions (FR-038). Dry run by default: prints the regions.

    --write rewrites cameras.yaml with the new blind_regions; YAML comments are lost.
    """
    from vigil.ingest.config import ConfigError, privacy_polygons
    from vigil.spatial.calibrate import load_calibrations
    from vigil.spatial.coverage import coverage, write_blind_regions

    cfg_path = _config_path(config)
    cfg = _load_cfg(cfg_path)
    cal_path = (
        Path(calibration) if calibration is not None else cfg_path.parent / "calibration.json"
    )
    if not cal_path.exists():
        _blocked(f"no camera calibration at {cal_path}: run `vigil spatial calibrate` (T-14)")
    if site_plan is None or not Path(site_plan).exists():
        _blocked(
            "coverage needs the LiDAR model (T-06) or a measured site plan (--site-plan); "
            "none given"
        )
    try:
        cams = load_calibrations(cal_path)
    except (ValueError, json.JSONDecodeError) as err:
        _fail(f"{cal_path}: {err}")
    if not cams:
        _blocked(f"{cal_path} has no calibrated cameras (T-14)")
    try:
        if Path(site_plan).suffix.lower() == ".glb":
            from vigil.spatial.glb import load_glb_scene

            scene = load_glb_scene(site_plan)
        else:
            scene = _scene_from_site_plan(_read_json(site_plan))
    except (KeyError, IndexError, TypeError, ValueError) as err:
        _fail(f"{site_plan}: site plan is malformed: {err}")
    try:
        privacy = {
            c.camera_id: privacy_polygons(cfg, c.camera_id, privacy_dir=cfg_path.parent / "privacy")
            for c in cams
        }
    except ConfigError as err:
        _fail(f"config: {err}")
    cov = coverage(scene, cams, privacy, cell_m, max_range_m=max_range_m)

    for r in cov.regions:
        typer.echo(f"{r.id}: {r.name} ({len(r.polygon_m)} vertices)")
    typer.echo(_dump([r.model_dump(mode="json") for r in cov.regions]))
    if grid_out is not None:
        _write_json(grid_out, cov.to_dict())
        typer.echo(f"coverage grid written to {grid_out}")
    if not write:
        typer.echo("dry run: cameras.yaml not changed; pass --write to update blind_regions")
        return
    try:
        path = write_blind_regions(cfg_path, cov.regions, replace_all=replace_all)
    except ValueError as err:
        _fail(f"updated config would be invalid: {err}")
    typer.secho(
        f"warning: rewrote {path}; its YAML comments are lost (review the diff)",
        fg="yellow",
        err=True,
    )


# ---------------------------------------------------------------------------
# cost (FR-043, spec 11.4)
# ---------------------------------------------------------------------------

# Spec 11.4 volume assumptions, one row per paid line: (feature, label, model, calls,
# per-call units). "clip" is replaced by --spark-clip-tokens (30,000 until T-03 measures it).
# Per-call tokens not stated in the spec are planning guesses, marked "assumed".
PLAN_11_4: list[tuple[str, str, str, int, dict[str, Any]]] = [
    ("smoke", "SAM video, 1 to 3 per model", "sam-3.1", 3, {"frames": 50}),
    ("smoke", "SAM image", "sam-3.1", 3, {"images": 1}),
    ("smoke", "Spark clip", "muse-spark-1.3", 3, {"in_tokens": "clip", "out_tokens": 500}),
    ("smoke", "Wonder story", "muse-wonder-1.0", 3, {"in_tokens": 6000, "out_tokens": 800}),
    ("smoke", "Voice 10 s", "muse-voice-transcribe-1.0", 3, {"audio_s": 10}),
    ("perception_demo", "5 scenarios x 4 cams x 3 phrases x 60 s x 10 fps", "sam-3.1", 60,
     {"frames": 600}),
    ("appearance", "~390 clips (290 benchmark + 100 dev), 500 out assumed", "muse-spark-1.3",
     390, {"in_tokens": "clip", "out_tokens": 500}),
    ("story", "~100 calls at 6k in / 0.8k out", "muse-wonder-1.0", 100,
     {"in_tokens": 6000, "out_tokens": 800}),
    ("triage", "~50 fallback calls, 6k in / 200 out assumed", "muse-spark-1.3", 50,
     {"in_tokens": 6000, "out_tokens": 200}),
    ("rule_compile", "~25 Spark text compiles, 2k in / 400 out assumed", "muse-spark-1.3", 25,
     {"in_tokens": 2000, "out_tokens": 400}),
    ("rule_compile", "~25 SAM tap-to-protect images", "sam-3.1", 25, {"images": 1}),
    ("baseline", "~70 clips, 300 out assumed", "muse-spark-1.3", 70,
     {"in_tokens": "clip", "out_tokens": 300}),
    ("voice", "a few minutes (10 x 30 s)", "muse-voice-transcribe-1.0", 10, {"audio_s": 30}),
]  # fmt: skip
PLAN_API_SAM: list[tuple[str, str, str, int, dict[str, Any]]] = [
    ("perception_all", "12 scenarios x 4 cams x 3 phrases x 750 frames (H-02 failed)",
     "sam-3.1", 144, {"frames": 750}),
]  # fmt: skip
# Capped lines (no volume, the spend is the cap): spec 11.4 and 11.5.
PLAN_CAPS: list[tuple[str, str, float]] = [
    ("sandbox", "hosted sandbox live buttons, $10/day x 2 days", 20.0),
    ("video", "live calls while recording the video", 2.0),
]
PLAN_CAPS_API_SAM: list[tuple[str, str, float]] = [
    ("live_home", "live home testing through the API (H-02 failed)", 15.0),
]


def plan_estimates(spark_clip_tokens: int, api_sam: bool) -> list:
    """CostEstimate per paid call of the spec 11.4 plan (each row repeated ``calls`` times)."""
    from vigil.meta.budget import estimate

    rows = PLAN_11_4 + (PLAN_API_SAM if api_sam else [])
    out = []
    for feature, _label, model, calls, units in rows:
        kw = {k: (spark_clip_tokens if v == "clip" else v) for k, v in units.items()}
        out += [estimate(model, feature, **kw)] * calls
    return out


@cost.command("estimate")
def cost_estimate(
    spark_clip_tokens: Annotated[
        int, typer.Option(help="Measured Spark input tokens per 10 s clip (T-03).")
    ] = 30_000,
    api_sam: Annotated[
        bool, typer.Option(help="Plan for API SAM on all scenarios (H-02 failed).")
    ] = False,
    model: Annotated[
        str | None, typer.Option(help="Ad-hoc estimate for one model instead of the plan.")
    ] = None,
    feature: Annotated[str, typer.Option(help="Ad-hoc: feature budget.")] = "other",
    calls: Annotated[int, typer.Option(help="Ad-hoc: number of identical calls.")] = 1,
    frames: Annotated[int, typer.Option(help="Ad-hoc: SAM video frames per call.")] = 0,
    images: Annotated[int, typer.Option(help="Ad-hoc: SAM images per call.")] = 0,
    in_tokens: Annotated[int, typer.Option(help="Ad-hoc: input tokens per call.")] = 0,
    out_tokens: Annotated[int, typer.Option(help="Ad-hoc: output tokens per call.")] = 0,
    audio_s: Annotated[float, typer.Option(help="Ad-hoc: audio seconds per call.")] = 0.0,
) -> None:
    """Recompute the spec 11.4 cost table (or price an ad-hoc batch with --model).

    Prices come from the spec 11.3 table in vigil/meta/budget.py; nothing is sent.
    """
    from vigil.meta.budget import FEATURE_CAPS, estimate, preflight

    cap = float(_settings().total_cap_usd)
    if model is not None:
        try:
            one = estimate(
                model, feature, in_tokens=in_tokens, out_tokens=out_tokens, frames=frames,
                images=images, audio_s=audio_s,
            )  # fmt: skip
        except (ValueError, KeyError) as err:
            _fail(err)
        summary = preflight([one] * max(calls, 0), confirm=True)
        for line in summary.lines():
            typer.echo(line)
        return

    summary = preflight(plan_estimates(spark_clip_tokens, api_sam), confirm=True)
    caps = PLAN_CAPS + (PLAN_CAPS_API_SAM if api_sam else [])
    lines = dict(summary.by_feature)
    for feat, _label, usd in caps:
        lines[feat] = lines.get(feat, 0.0) + usd
    scenario = "API SAM (H-02 failed)" if api_sam else "local SAM (H-02 passed)"
    typer.echo(f"spec 11.4 plan, {scenario}; Spark clip = {spark_clip_tokens:,} input tokens")
    over = []
    for feat, usd in sorted(lines.items()):
        fcap = FEATURE_CAPS.get(feat)
        flag = ""
        if fcap is not None and usd > fcap + 1e-9:
            flag = "  OVER feature budget"
            over.append(feat)
        cap_txt = f" / ${fcap:.2f}" if fcap is not None else ""
        typer.echo(f"  {feat:<16} ${usd:8.2f}{cap_txt}{flag}")
    total = sum(lines.values())
    typer.echo(f"total ${total:.2f} of the ${cap:.2f} cap ({100 * total / cap:.0f}%)")
    typer.echo(f"reserve ${cap - total:.2f}")
    if over:
        typer.secho(
            f"over feature budget: {', '.join(over)}; update spec 11.4 before spending",
            fg="yellow",
        )
    if total > cap:
        typer.secho("plan exceeds the total cap", fg="red", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
