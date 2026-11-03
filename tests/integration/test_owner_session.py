"""FIXTURE: the browser's persisted owner state feeds the same session processor."""

from datetime import timedelta
from pathlib import Path

import pytest

from tests.fixtures.scenarios.builders import SCENARIOS
from tests.integration.test_contracts import _write_session
from vigil.models import CheckIn
from vigil.pipeline import process_session
from vigil.settings import Settings
from vigil.store import db


def test_process_reads_and_consumes_persisted_owner_checkin(tmp_path):
    scenario = SCENARIOS["B-prime"]()
    data = tmp_path / "data"
    _write_session(data, "owner", scenario, sam=True)
    settings = Settings(
        _env_file=None,
        mode="edge",
        config_path=Path(__file__).parents[1] / "fixtures/config/synthetic-cameras.yaml",
        data_dir=data,
        db_path=tmp_path / "owner.db",
    )
    tap = scenario.session_start + timedelta(seconds=1)
    conn = db.open_db(settings.db_path)
    with conn:
        db.insert_checkin(
            conn, CheckIn(id="owner-tap", start=tap, expires=tap + timedelta(minutes=30))
        )
    conn.close()
    result = process_session("owner", settings=settings)
    subject = result["visits"][0]["subjects"][0]
    assert subject["actor_role"] == "household_insider"
    assert subject["role_basis"] == "checkin:owner-tap"
    replay = process_session("owner", settings=settings)
    assert replay["visits"][0]["subjects"][0]["actor_role"] == "household_insider"
    assert replay["visits"][0]["subjects"][0]["role_basis"] == "checkin:owner-tap"
    conn = db.connect(settings.db_path)
    try:
        assert db.checkins(conn)[0].bound_subject == subject["id"]
    finally:
        conn.close()
    _write_session(data, "later", scenario, sam=True)
    later = process_session("later", settings=settings)
    assert later["visits"][0]["subjects"][0]["actor_role"] == "external_visitor"


@pytest.mark.parametrize("cancelled", [False, True])
def test_process_uses_persisted_windows_and_cancellations(tmp_path, cancelled):
    scenario = SCENARIOS["B-prime"]()
    data = tmp_path / "data"
    extra = scenario.session_json() if cancelled else None
    _write_session(data, "owner", scenario, sam=True, extra=extra)
    settings = Settings(
        _env_file=None,
        mode="edge",
        config_path=Path(__file__).parents[1] / "fixtures/config/synthetic-cameras.yaml",
        data_dir=data,
        db_path=tmp_path / "owner.db",
    )
    window = scenario.expected_windows[0]
    if cancelled:
        window = window.model_copy(update={"state": "cancelled"})
    conn = db.open_db(settings.db_path)
    with conn:
        db.insert_expected_window(conn, window)
    conn.close()
    result = process_session("owner", settings=settings)
    expected = "external_visitor" if cancelled else "expected_visitor"
    assert result["visits"][0]["subjects"][0]["actor_role"] == expected
