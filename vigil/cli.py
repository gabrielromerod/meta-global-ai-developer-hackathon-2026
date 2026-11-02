"""`vigil` command line (spec 9.2: typer). Subcommands are wired to modules as they land.

Batch commands that can spend money print a pre-flight estimate first and need --confirm
above $5 (spec 11.6, safeguard 3).
"""

from __future__ import annotations

from pathlib import Path

import typer

from vigil import __version__

app = typer.Typer(help="Vigil: one cited story per visit.", no_args_is_help=True)
spatial = typer.Typer(help="LiDAR model, calibration and coverage (FR-035 to FR-038).")
reolink = typer.Typer(help="Reolink probe and capture (FR-030, FR-031).")
cost = typer.Typer(help="Budget estimates (FR-043).")
app.add_typer(spatial, name="spatial")
app.add_typer(reolink, name="reolink")
app.add_typer(cost, name="cost")


def _todo(what: str) -> None:
    typer.secho(f"{what}: not implemented yet (see docs/readiness.md)", fg="yellow", err=True)
    raise typer.Exit(code=2)


@app.command()
def version() -> None:
    """Print the Vigil version."""
    typer.echo(__version__)


@app.command()
def ingest(clip_dir: Path, session: str = "default") -> None:
    """Sync, mask and window raw clips (FR-002 to FR-005)."""
    _todo("ingest")


@app.command()
def process(session: str = "default", confirm: bool = False) -> None:
    """Run perception and reasoning on a session (pre-flight estimate first)."""
    _todo("process")


@app.command(name="eval")
def eval_(
    labels: Path = Path("eval/labels"),
    out: Path = Path("eval/results.json"),
    latency: bool = False,
    spatial_: bool = typer.Option(False, "--spatial"),
    confirm: bool = False,
) -> None:
    """Compute EVAL metrics against pre-registered labels (FR-024)."""
    from vigil.eval.run import run_eval

    try:
        run_eval(labels, out)
    except NotImplementedError:
        _todo("eval")


@app.command()
def export(out: Path = Path("demo")) -> None:
    """Write the demo bundle (FR-027)."""
    from vigil.store.export import export_bundle

    try:
        export_bundle(out)
    except NotImplementedError:
        _todo("export")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the web app and API (sandbox or LAN)."""
    import uvicorn

    uvicorn.run("vigil.api.app:create_app", host=host, port=port, factory=True)


@spatial.command("build")
def spatial_build(scan_dir: Path) -> None:
    """Build the house model from LiDAR segments (FR-035)."""
    _todo("spatial build")


@spatial.command("calibrate")
def spatial_calibrate(camera: str) -> None:
    """Calibrate one camera into the model (FR-036, FR-037)."""
    _todo("spatial calibrate")


@spatial.command("coverage")
def spatial_coverage() -> None:
    """Compute coverage and blind regions (FR-038)."""
    _todo("spatial coverage")


@reolink.command("probe")
def reolink_probe() -> None:
    """Probe every configured camera (FR-030)."""
    _todo("reolink probe")


@reolink.command("capture")
def reolink_capture(out_dir: Path = Path("data/segments")) -> None:
    """Run continuous capture (FR-031)."""
    _todo("reolink capture")


@cost.command("estimate")
def cost_estimate() -> None:
    """Recompute the spec 11.4 cost table from measured token counts."""
    _todo("cost estimate")


if __name__ == "__main__":
    app()
