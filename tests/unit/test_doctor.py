"""Offline handover diagnostics: presence/readiness, never authentication or camera probes."""

from typer.testing import CliRunner

from vigil.cli import app


def test_doctor_missing_prerequisites_are_named(tmp_path, monkeypatch):
    for key in ("MODEL_API_KEY", "VIGIL_CREDIT_WINDOW_END", "VIGIL_LEDGER_PATH"):
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / "cameras.yaml"
    config.write_text(
        "cameras:\n- id: front\n  name: Front\n  source: {host_env: DOCTOR_FRONT_HOST}\n"
    )
    result = CliRunner().invoke(
        app, ["doctor", "--env-file", str(tmp_path / "missing.env"), "--config", str(config)]
    )
    assert result.exit_code == 1, result.output
    for label in (
        "MODEL_API_KEY",
        "VIGIL_CREDIT_WINDOW_END",
        "VIGIL_LEDGER_PATH",
        "privacy:front",
        "DOCTOR_FRONT_HOST",
    ):
        assert f"MISSING {label}" in result.output


def test_doctor_has_no_network_paths(tmp_path, monkeypatch):
    # With the normal networking clients disabled, even missing-prerequisite diagnostics
    # must run and exit cleanly; this also prevents accidental live checks in doctor.
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("doctor must not use the network")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    result = CliRunner().invoke(app, ["doctor", "--env-file", str(tmp_path / "missing.env")])
    assert result.exit_code == 1, result.output
    assert "MISSING" in result.output


def test_doctor_ready_configuration_never_echoes_secrets(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from vigil import doctor
    from vigil.settings import Settings

    for name in (
        "MODEL_API_KEY",
        "VIGIL_MODE",
        "VIGIL_META_CACHE_ONLY",
        "VIGIL_CREDIT_WINDOW_END",
        "VIGIL_JUDGING_END",
        "VIGIL_LEDGER_PATH",
        "VIGIL_OWNER_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / "fixture.env"
    env.write_text(
        "MODEL_API_KEY=fixture-meta-secret\nVIGIL_MODE=edge\n"
        "VIGIL_CREDIT_WINDOW_END=2026-11-05T00:00:00Z\n"
        "VIGIL_JUDGING_END=2026-11-10T23:59:00-08:00\n"
        f"VIGIL_LEDGER_PATH={(tmp_path / 'ledger.db').as_posix()}\n"
        "VIGIL_OWNER_TOKEN=fixture-owner-secret\nREOLINK_USER=fixture-user\n"
        "REOLINK_PASSWORD=fixture-camera-secret\nDOCTOR_FRONT_HOST=192.0.2.10\n"
    )
    config = tmp_path / "cameras.yaml"
    config.write_text(
        "evidence_kind: fixture\ncameras:\n- id: front\n  name: Front\n  privacy: none_needed\n"
        "  source: {host_env: DOCTOR_FRONT_HOST}\n"
    )
    settings = Settings(_env_file=env, config_path=config)
    monkeypatch.setattr(doctor, "version", lambda name: "0.22.0")
    monkeypatch.setattr(doctor, "ffmpeg_bin", lambda settings: "ffmpeg")
    monkeypatch.setattr(doctor, "ffprobe_bin", lambda settings: "ffprobe")
    monkeypatch.setattr(
        doctor.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0)
    )
    checks = doctor.check_readiness(settings, env, now=datetime(2026, 11, 3, tzinfo=UTC))
    assert all(check.ready for check in checks), checks
    assert "fixture-meta-secret" not in repr(checks)
    assert "fixture-camera-secret" not in repr(checks)
    assert "192.0.2.10" not in repr(checks)
    expired = doctor.check_readiness(settings, env, now=datetime(2026, 11, 12, tzinfo=UTC))
    assert not next(c.ready for c in expired if c.name == "VIGIL_CREDIT_WINDOW_END")
    assert not next(c.ready for c in expired if c.name == "VIGIL_JUDGING_END")


def test_doctor_binary_resolvers_accept_explicit_settings():
    from vigil.settings import Settings, ffmpeg_bin, ffprobe_bin

    settings = Settings(_env_file=None, ffmpeg="fixture-ffmpeg", ffprobe="fixture-ffprobe")
    assert ffmpeg_bin(settings) == "fixture-ffmpeg"
    assert ffprobe_bin(settings) == "fixture-ffprobe"


def test_doctor_real_inventory_privacy_power_hub_clock_and_exiftool(tmp_path):
    from pathlib import Path

    from vigil.doctor import check_readiness
    from vigil.settings import Settings

    settings = Settings(
        _env_file=None, config_path=Path(__file__).parents[2] / "config/cameras.yaml"
    )
    checks = {c.name: c for c in check_readiness(settings, tmp_path / "missing.env")}
    assert checks["exiftool"].ready
    for camera in (
        "front_left_duo",
        "front_right_duo",
        "doorbell",
        "porch",
        "side_left",
        "backyard_1",
        "backyard_2",
    ):
        assert checks["power:" + camera].ready
        assert not checks["privacy:" + camera].ready
        assert not checks["clock:" + camera].ready
    assert checks["hub:side_left"].ready
    assert "import" in checks["hub:side_left"].detail.lower()
