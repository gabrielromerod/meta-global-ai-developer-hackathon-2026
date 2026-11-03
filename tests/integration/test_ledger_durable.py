"""Durable spend ledger (FR-043, NFR-036, NFR-037, spec 11.6): caps survive a restart.

The call ledger is a SQLite file at VIGIL_LEDGER_PATH (WAL, one row per call with funding,
feature, cost and a UTC timestamp). The Meta client's budget guard and the sandbox guards both
derive their spent totals from it, so a container restart does not hand out a fresh $25
judging cap, $5 PT day or $140 credit cap. Without a durable ledger, paid calls fail closed.
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from vigil.api.guards import NOTICE_BUDGET, Guards
from vigil.meta.budget import BudgetExceeded
from vigil.meta.client import CallLedger, MetaClient, reset_shared_ledgers, shared_ledger
from vigil.models import ModelCall
from vigil.settings import Settings

BASE = "https://api.meta.ai/v1"
KEY = "sk-test-durable-ledger"
NOW = datetime(2026, 11, 6, 20, 0, tzinfo=UTC)  # Nov 6 12:00 PT: judging period
PT = ZoneInfo("America/Los_Angeles")
REPO_ROOT = Path(__file__).resolve().parents[2]
OK_BODY = {
    "id": "resp_1",
    "status": "completed",
    "output_text": '{"escalate": false}',
    "usage": {"input_tokens": 1000, "output_tokens": 100},
}
SPARK_COST = 1000 * 1.25 / 1e6 + 100 * 4.25 / 1e6
BODY = {"input": "hello", "max_output_tokens": 200}


@pytest.fixture(autouse=True)
def _fresh_registry() -> Iterator[None]:
    reset_shared_ledgers()
    yield
    reset_shared_ledgers()


@pytest.fixture
def router():
    with respx.mock(base_url=BASE, assert_all_called=False) as r:
        yield r


def _settings(tmp_path: Path, **kw: Any) -> Settings:
    base: dict[str, Any] = {
        "MODEL_API_KEY": KEY,
        "cache_dir": tmp_path / "cache",
        "ledger_path": tmp_path / "data" / "ledger.db",
        "credit_window_end": datetime(2026, 11, 5, 5, 59, tzinfo=PT),
        "allow_paid": True,
        "judging_end": datetime(2026, 11, 10, 23, 59, tzinfo=PT),
    }
    base.update(kw)
    return Settings(_env_file=None, **base)


def _client(settings: Settings, now: datetime = NOW) -> MetaClient:
    return MetaClient(settings, clock=lambda: now, sleep=lambda s: None, rng=random.Random(0))


def _paid_row(cost: float, when: datetime, i: int = 0) -> ModelCall:
    return ModelCall(
        id=f"seed{i}", model="muse-spark-1.3", purpose="sandbox_compile", req_hash="h",
        cost_usd=cost, feature="sandbox", funding="paid", created_at=when,
    )  # fmt: skip


# --- the file ------------------------------------------------------------------------------


def test_ledger_is_sqlite_wal_with_one_utc_row_per_call(tmp_path: Path):
    path = tmp_path / "ledger.db"
    ledger = CallLedger(path)
    assert ledger.durable is True
    pt_time = datetime(2026, 11, 6, 9, 30, tzinfo=PT)
    ledger.add(_paid_row(0.5, pt_time))
    ledger.close()
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        row = con.execute(
            "SELECT funding, feature, cost_usd, created_at FROM model_calls"
        ).fetchone()
    funding, feature, cost, created_at = row
    assert (funding, feature, cost) == ("paid", "sandbox", 0.5)
    assert created_at == "2026-11-06T17:30:00+00:00"  # stored in UTC


def test_unwritable_ledger_path_degrades_to_memory_without_crashing(tmp_path: Path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    ledger = CallLedger(blocker / "ledger.db")
    assert ledger.durable is False
    ledger.add(_paid_row(0.1, NOW))  # still recorded in memory
    assert ledger.total() == pytest.approx(0.1)


def test_ledger_write_failure_marks_it_not_durable(tmp_path: Path):
    ledger = CallLedger(tmp_path / "ledger.db")
    assert ledger.durable is True
    ledger._con.close()  # the disk goes away under the running process
    ledger.add(_paid_row(0.2, NOW))
    assert ledger.durable is False
    assert ledger.book.durable is False
    assert ledger.total() == pytest.approx(0.2)


# --- F1: caps survive a restart --------------------------------------------------------------


def test_client_caps_survive_a_restart(tmp_path: Path, router):
    settings = _settings(tmp_path)
    route = router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    first = _client(settings)
    assert first.ledger.durable is True
    first.ledger.add(_paid_row(24.999, NOW - timedelta(days=1)))  # earlier judging spend
    first.responses("muse-spark-1.3", BODY, purpose="triage")
    assert first.budget.spent_paid == pytest.approx(24.999 + SPARK_COST)
    first.close()

    reset_shared_ledgers()  # the process restarts: nothing survives but the file
    second = _client(settings)
    assert second.ledger is not first.ledger
    assert second.budget.spent_paid == pytest.approx(24.999 + SPARK_COST)
    with pytest.raises(BudgetExceeded) as exc:
        second.responses("muse-spark-1.3", {**BODY, "input": "new"}, purpose="triage")
    assert exc.value.cap == "judging"
    assert route.call_count == 1
    second.close()


def test_client_daily_paid_cap_survives_a_restart(tmp_path: Path, router):
    settings = _settings(tmp_path)
    router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    first = _client(settings)
    first.ledger.add(_paid_row(4.9995, NOW - timedelta(hours=1)))
    first.close()
    reset_shared_ledgers()
    second = _client(settings)
    assert second.budget.spent_paid_today() == pytest.approx(4.9995)
    with pytest.raises(BudgetExceeded) as exc:
        second.responses("muse-spark-1.3", BODY, purpose="triage")
    assert exc.value.cap == "judging_daily"


def test_guards_caps_survive_a_restart(tmp_path: Path):
    settings = _settings(tmp_path)
    clock = lambda: NOW.timestamp()  # noqa: E731
    guards = Guards(settings, clock=clock)
    assert guards.phase() == ("judging", None)
    guards.record_spend(4.99, "paid")
    assert guards.spend_today("paid") == pytest.approx(4.99)

    reset_shared_ledgers()
    restarted = Guards(settings, clock=clock)
    assert restarted.spend_today("paid") == pytest.approx(4.99)
    assert restarted.spend_total("paid") == pytest.approx(4.99)
    status = restarted.live_status(0.02)
    assert status.available is False
    assert status.reason == "judging_daily_cap"
    assert status.notice == NOTICE_BUDGET


def test_guards_credit_daily_cap_survives_a_restart(tmp_path: Path):
    settings = _settings(tmp_path, credit_window_end=None, allow_paid=False)
    clock = lambda: datetime(2026, 11, 2, 20, 0, tzinfo=UTC).timestamp()  # noqa: E731
    Guards(settings, clock=clock).record_spend(9.99, "credit")
    reset_shared_ledgers()
    status = Guards(settings, clock=clock).live_status(0.02)
    assert status.reason == "spend_cap"
    assert status.notice == NOTICE_BUDGET


# --- one ledger per process: the sandbox guards and the live client share it ----------------


def test_guards_and_live_client_share_one_ledger_without_double_counting(
    tmp_path: Path, router, monkeypatch
):
    from vigil.api.backend import MetaLiveBackend
    from vigil.meta import spark

    far = datetime(2099, 1, 1, tzinfo=UTC)
    settings = _settings(tmp_path, credit_window_end=None, allow_paid=False, judging_end=far)
    router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))

    def fake_compile(client: Any, text: str, catalog: dict) -> dict:
        client.responses("muse-spark-1.3", {"input": text}, purpose="rule_compile")
        return {"rule": {"id": "r1"}}

    monkeypatch.setattr(spark, "compile_rule", fake_compile)
    guards = Guards(settings)
    backend = MetaLiveBackend(settings)
    res = backend.compile_rule("tell me if anyone opens the gate", {})
    client = backend._meta_client()
    assert client.ledger is guards.ledger is shared_ledger(settings.ledger_path)
    cost = sum(c.cost_usd for c in res.calls)
    assert cost == pytest.approx(SPARK_COST)
    # The route records the live result's spend: it is already in the ledger, so it is not
    # counted twice.
    guards.record_spend(cost, "credit")
    assert guards.spend_today("credit") == pytest.approx(SPARK_COST)
    assert guards.ledger.total() == pytest.approx(SPARK_COST)
    # record_calls de-duplicates by call id.
    guards.record_calls(res.calls)
    assert guards.ledger.total() == pytest.approx(SPARK_COST)
    client.close()


def test_app_live_client_shares_the_guards_ledger_without_a_ledger_path(tmp_path: Path):
    """In memory (VIGIL_LEDGER_PATH unset) the sandbox guards and the live client still keep
    one ledger, so their totals and reservations agree."""
    from vigil.api.app import create_app

    settings = _settings(tmp_path, credit_window_end=None, allow_paid=False, ledger_path=None)
    app = create_app(settings)
    client = app.state.live_backend._meta_client()
    try:
        assert client.ledger is app.state.guards.ledger
    finally:
        client.close()


def test_accept_live_records_new_calls_despite_a_stale_prerecorded_offer(tmp_path: Path):
    """The route ledgers a live result by call id, not by amount: spend the client offered
    as pre-recorded for an action that never reached the route must not absorb the next
    action's new calls."""
    from types import SimpleNamespace

    from vigil.api.backend import LiveResult
    from vigil.api.routes import Runtime, _accept_live

    settings = _settings(tmp_path, credit_window_end=None, allow_paid=False)
    clock = lambda: datetime(2026, 11, 2, 20, 0, tzinfo=UTC).timestamp()  # noqa: E731
    guards = Guards(settings, clock=clock)
    guards.book.offer_prerecorded(0.5)  # an earlier action failed after its calls were ledgered
    call = ModelCall(id="call_new", model="muse-spark-1.3", purpose="rule_compile",
                     req_hash="h", cost_usd=0.5)  # fmt: skip
    _accept_live(guards, Runtime(SimpleNamespace(rules=[])), LiveResult(payload={}, calls=[call]))
    assert guards.spend_today("credit") == pytest.approx(0.5)
    assert guards.ledger.has("call_new")


def test_record_calls_adds_rows_the_ledger_has_not_seen(tmp_path: Path):
    settings = _settings(tmp_path, credit_window_end=None, allow_paid=False)
    clock = lambda: datetime(2026, 11, 2, 20, 0, tzinfo=UTC).timestamp()  # noqa: E731
    guards = Guards(settings, clock=clock)
    call = ModelCall(id="call_x", model="sam-3.1", purpose="protect", req_hash="h", cost_usd=1.5)
    guards.record_calls([call])
    guards.record_calls([call])
    assert guards.spend_today("credit") == pytest.approx(1.5)
    reset_shared_ledgers()
    assert Guards(settings, clock=clock).spend_today("credit") == pytest.approx(1.5)


# --- fail closed when the ledger is not durable --------------------------------------------


def test_unwritable_path_never_crashes_startup_and_refuses_paid(tmp_path: Path):
    from fastapi.testclient import TestClient

    from vigil.api.app import create_app

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    settings = _settings(tmp_path, mode="sandbox", ledger_path=blocker / "ledger.db")
    guards = Guards(settings, clock=lambda: NOW.timestamp())
    assert guards.ledger.durable is False
    status = guards.live_status(0.01)
    assert status.available is False
    assert status.reason == "ledger_not_durable"
    assert status.notice == NOTICE_BUDGET
    # Credit-window live calls are unaffected by an in-memory ledger.
    credit = _settings(tmp_path, ledger_path=blocker / "ledger.db", credit_window_end=None)
    in_window = Guards(credit, clock=lambda: datetime(2026, 11, 2, tzinfo=UTC).timestamp())
    assert in_window.live_status(0.01).available is True
    # The sandbox starts and serves health.
    app = create_app(settings)
    assert TestClient(app).get("/api/health").status_code == 200


# --- the container keeps the ledger on a volume ---------------------------------------------


def test_dockerfile_keeps_the_ledger_on_a_volume():
    text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "VIGIL_LEDGER_PATH=/data/ledger.db" in text
    assert 'VOLUME ["/data"]' in text
    assert "single replica" in text.lower()
