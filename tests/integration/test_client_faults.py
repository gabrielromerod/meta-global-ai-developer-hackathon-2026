"""MetaClient fault injection with respx (NFR-010, FR-023, FR-026, NFR-004, spec section 3).

No network: respx intercepts every request. Sleep is injected, so backoff is instant.
"""

from __future__ import annotations

import json
import random
import sqlite3
import struct
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from vigil.meta.budget import BudgetExceeded, BudgetGuard, PaidCallsDisabled
from vigil.meta.cache import ResponseCache, request_hash
from vigil.meta.client import (
    CacheMiss,
    CallLedger,
    MalformedResponse,
    MetaClient,
    MetaHTTPError,
    MetaUnavailable,
    ModelNotAllowed,
    estimate_request,
    extract_text,
)
from vigil.models import VisitSummary
from vigil.settings import Settings

BASE = "https://api.meta.ai/v1"
KEY = "sk-test-NEVER-LOG-ME-123"
NOW = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)

OK_BODY = {
    "id": "resp_1",
    "object": "response",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": '{"escalate": false, "reason": "ok"}'}],
        }
    ],
    "usage": {
        "input_tokens": 1000,
        "output_tokens": 100,
        "input_tokens_details": {"cached_tokens": 0},
        "total_tokens": 1100,
    },
}
SPARK_COST = 1000 * 1.25 / 1e6 + 100 * 4.25 / 1e6
BODY = {"input": "hello", "max_output_tokens": 200}


class Env:
    def __init__(self, tmp_path: Path, durable: bool = False, **settings_kw):
        settings_kw.setdefault("MODEL_API_KEY", KEY)
        self.settings = Settings(_env_file=None, cache_dir=tmp_path / "cache", **settings_kw)
        self.sleeps: list[float] = []
        # Paid calls need a durable ledger (fail closed); credit-window tests stay in memory.
        self.ledger = CallLedger(tmp_path / "ledger.db") if durable else CallLedger()
        self.cache = ResponseCache(tmp_path / "cache")
        self.guard = BudgetGuard(self.settings, clock=lambda: NOW, ledger=self.ledger)
        self.tmp_path = tmp_path

    def client(self, **kw) -> MetaClient:
        kw.setdefault("ledger", self.ledger)
        kw.setdefault("cache", self.cache)
        kw.setdefault("budget", self.guard)
        return MetaClient(
            self.settings,
            clock=lambda: NOW,
            sleep=self.sleeps.append,
            rng=random.Random(0),
            **kw,
        )


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def router():
    with respx.mock(base_url=BASE, assert_all_called=False) as r:
        yield r


# --- retries (spec section 3: test_client_retry) -----------------------------------------


def test_client_retry(env: Env, router):
    """429 then 200: succeeds after one backoff; one ledger row with the real cost."""
    route = router.post("/responses").mock(
        side_effect=[
            httpx.Response(429, json={"error": {"code": "rate_limit_exceeded"}}),
            httpx.Response(200, json=OK_BODY),
        ]
    )
    resp = env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert route.call_count == 2
    assert len(env.sleeps) == 1
    assert extract_text(resp) == '{"escalate": false, "reason": "ok"}'
    assert resp["_vigil"]["cached"] is False
    [row] = env.ledger.rows()
    assert row.ok
    assert not row.cached
    assert row.model == "muse-spark-1.3"
    assert row.purpose == "triage"
    assert row.in_tokens == 1000
    assert row.out_tokens == 100
    assert row.cost_usd == pytest.approx(SPARK_COST)
    assert row.latency_ms is not None
    assert row.latency_ms >= 0
    assert resp["_vigil"]["call_id"] == row.id


def test_client_retry_gives_up_after_two_retries_on_5xx(env: Env, router):
    route = router.post("/responses").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(MetaUnavailable) as exc:
        env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert route.call_count == 3  # 1 try + 2 retries
    assert exc.value.fallback is True
    assert exc.value.status == 500
    assert len(env.sleeps) == 2
    assert env.sleeps[1] > env.sleeps[0]  # exponential
    [row] = env.ledger.rows()
    assert not row.ok
    assert row.error
    assert row.cost_usd == 0


def test_client_retry_honours_retry_after(env: Env, router):
    router.post("/responses").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(200, json=OK_BODY),
        ]
    )
    env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert env.sleeps[0] >= 3.0


def test_client_timeout_retried_then_fallback(env: Env, router):
    route = router.post("/responses").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(MetaUnavailable) as exc:
        env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert route.call_count == 3
    assert exc.value.fallback is True
    assert "timeout" in str(exc.value)


def test_client_timeout_then_success(env: Env, router):
    router.post("/responses").mock(
        side_effect=[httpx.ConnectTimeout("t"), httpx.Response(200, json=OK_BODY)]
    )
    resp = env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert resp["id"] == "resp_1"


def test_client_malformed_json(env: Env, router):
    route = router.post("/responses").mock(
        return_value=httpx.Response(200, text="{not json", headers={"content-type": "text/plain"})
    )
    with pytest.raises(MalformedResponse) as exc:
        env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert isinstance(exc.value, MetaUnavailable)
    assert exc.value.fallback is True
    assert route.call_count == 3
    [row] = env.ledger.rows()
    assert not row.ok
    # Every 200 may have been billed: the guard is charged the estimate for each, conservatively.
    est = estimate_request("muse-spark-1.3", "triage", {**BODY, "model": "muse-spark-1.3"})
    assert exc.value.billed_attempts == 3
    assert row.cost_usd == pytest.approx(3 * est.usd)
    assert env.guard.spent_total == pytest.approx(env.ledger.total())


def test_client_400_not_retried(env: Env, router):
    err = {"error": {"type": "invalid_request_error", "message": "point outside the frame"}}
    route = router.post("/responses").mock(return_value=httpx.Response(400, json=err))
    with pytest.raises(MetaHTTPError) as exc:
        env.client().responses("sam-3.1", BODY, purpose="segment_point", units={"images": 1})
    assert route.call_count == 1
    assert env.sleeps == []
    assert exc.value.status == 400
    assert exc.value.fallback is False
    assert "point outside the frame" in str(exc.value)
    assert "point outside the frame" in exc.value.body


def test_failed_status_with_server_error_is_retried(env: Env, router):
    failed = {"id": "r", "status": "failed", "error": {"code": "server_error", "message": "x"}}
    router.post("/responses").mock(
        side_effect=[httpx.Response(200, json=failed), httpx.Response(200, json=OK_BODY)]
    )
    assert env.client().responses("muse-spark-1.3", BODY, purpose="triage")["id"] == "resp_1"


# --- F5: every billed attempt is counted; the budget is re-checked before each retry -----

NOT_JSON = {"text": "{not json", "headers": {"content-type": "text/plain"}}


def _spark_est():
    return estimate_request("muse-spark-1.3", "triage", {**BODY, "model": "muse-spark-1.3"})


def test_client_retry_counts_every_billed_attempt(env: Env, router):
    """non-JSON 200, 500, non-JSON 200: two billed attempts are charged, not one."""
    router.post("/responses").mock(
        side_effect=[
            httpx.Response(200, **NOT_JSON),
            httpx.Response(500, text="boom"),
            httpx.Response(200, **NOT_JSON),
        ]
    )
    with pytest.raises(MalformedResponse) as exc:
        env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert exc.value.attempts == 3
    assert exc.value.billed_attempts == 2
    [row] = env.ledger.rows()
    assert not row.ok
    assert row.cost_usd == pytest.approx(2 * _spark_est().usd)
    assert "2 billed" in (row.error or "")
    assert env.guard.spent_total == pytest.approx(2 * _spark_est().usd)


def test_client_retry_counts_a_billed_attempt_before_unbilled_ones(env: Env, router):
    """non-JSON 200, 500, 500: one billed attempt is charged although the last was a 500."""
    router.post("/responses").mock(
        side_effect=[
            httpx.Response(200, **NOT_JSON),
            httpx.Response(500, text="boom"),
            httpx.Response(500, text="boom"),
        ]
    )
    with pytest.raises(MetaUnavailable) as exc:
        env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert exc.value.billed_attempts == 1
    [row] = env.ledger.rows()
    assert row.cost_usd == pytest.approx(_spark_est().usd)
    assert env.guard.spent_total == pytest.approx(_spark_est().usd)


def test_client_success_after_billed_attempt_charges_both(env: Env, router):
    router.post("/responses").mock(
        side_effect=[httpx.Response(200, **NOT_JSON), httpx.Response(200, json=OK_BODY)]
    )
    resp = env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    [row] = env.ledger.rows()
    assert row.ok
    assert row.cost_usd == pytest.approx(_spark_est().usd + SPARK_COST)
    assert resp["_vigil"]["cost_usd"] == pytest.approx(row.cost_usd)
    assert env.guard.spent_total == pytest.approx(row.cost_usd)


def test_retry_cannot_cross_a_cap(env: Env, router):
    """The budget is checked again before a retry: a billed failure that leaves no room for
    another attempt stops the retries instead of crossing the cap."""
    est = _spark_est().usd
    env.guard.record(1.0 - 1.5 * est, "triage")  # triage feature budget is $1
    route = router.post("/responses").mock(return_value=httpx.Response(200, **NOT_JSON))
    with pytest.raises(BudgetExceeded) as exc:
        env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert exc.value.cap == "feature:triage"
    assert route.call_count == 1
    [row] = env.ledger.rows()
    assert not row.ok
    assert row.cost_usd == pytest.approx(est)
    assert env.guard.spent_feature("triage") <= 1.0 + 1e-9
    assert env.guard.spent_feature("triage") == pytest.approx(1.0 - 0.5 * est)


# --- F1 / F4: fail closed --------------------------------------------------------------


def test_paid_call_refused_without_a_durable_ledger(tmp_path: Path, router):
    """No VIGIL_LEDGER_PATH: the client's own ledger is in memory, so paid calls fail closed."""
    settings = Settings(
        _env_file=None,
        MODEL_API_KEY=KEY,
        cache_dir=tmp_path / "cache",
        credit_window_end=datetime(2026, 11, 1, tzinfo=UTC),
        allow_paid=True,
    )
    route = router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    client = MetaClient(settings, clock=lambda: NOW, sleep=lambda s: None)
    assert client.ledger.durable is False
    with pytest.raises(BudgetExceeded) as exc:
        client.responses("muse-spark-1.3", BODY, purpose="triage")
    assert exc.value.cap == "ledger"
    assert route.call_count == 0


def test_judging_end_refuses_live_calls_without_credit_window_end(tmp_path: Path, router):
    """VIGIL_CREDIT_WINDOW_END unset (every call tagged credit): still none after judging end."""
    after = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
    settings = Settings(
        _env_file=None, MODEL_API_KEY=KEY, cache_dir=tmp_path / "cache", credit_window_end=None
    )
    route = router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    client = MetaClient(settings, ledger=CallLedger(), clock=lambda: after, sleep=lambda s: None)
    with pytest.raises(BudgetExceeded) as exc:
        client.responses("muse-spark-1.3", BODY, purpose="triage")
    assert exc.value.cap == "judging_end"
    assert route.call_count == 0


# --- allowlist (NFR-004) -----------------------------------------------------------------


@pytest.mark.parametrize(
    "model", ["muse-spark-1.3-contributor", "muse-spark-1.2-contributor", "muse-image-1.0", "x"]
)
def test_client_refuses_contributor_and_unlisted_models(env: Env, router, model):
    route = router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    with pytest.raises(ModelNotAllowed):
        env.client().responses(model, BODY, purpose="triage")
    assert route.call_count == 0
    assert env.ledger.rows() == []


# --- cache (spec 11.6 item 4) ------------------------------------------------------------


def test_client_cached_second_call_costs_zero(env: Env, router):
    route = router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    c = env.client()
    first = c.responses("muse-spark-1.3", BODY, purpose="triage", visit_id="v1")
    second = c.responses("muse-spark-1.3", dict(reversed(BODY.items())), purpose="triage")
    # A fresh client over the same cache directory is also free.
    third = env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert route.call_count == 1
    assert extract_text(first) == extract_text(second) == extract_text(third)
    rows = env.ledger.rows()
    assert [r.cached for r in rows] == [False, True, True]
    assert rows[1].cost_usd == 0
    assert rows[2].cost_usd == 0
    assert rows[0].req_hash == rows[1].req_hash
    assert rows[0].visit_id == "v1"
    assert second["_vigil"]["cached"] is True
    assert env.guard.spent_total == pytest.approx(SPARK_COST)


def test_cache_only_mode_never_calls_network(env: Env, router):
    route = router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    with pytest.raises(CacheMiss) as exc:
        env.client(cache_only=True).responses("muse-spark-1.3", BODY, purpose="triage")
    assert exc.value.fallback is True
    assert route.call_count == 0


def test_request_hash_is_canonical():
    a = request_hash("muse-spark-1.3", {"b": 1, "a": [1, {"y": 2, "x": 1}]})
    b = request_hash("muse-spark-1.3", {"a": [1, {"x": 1, "y": 2}], "b": 1})
    assert a == b
    assert a != request_hash("muse-wonder-1.0", {"b": 1, "a": [1, {"y": 2, "x": 1}]})
    assert a != request_hash("muse-spark-1.3", {"b": 2, "a": [1, {"y": 2, "x": 1}]})


# --- ledger (FR-023) ---------------------------------------------------------------------


def test_ledger_total_equals_sum(env: Env, router, tmp_path: Path):
    db = tmp_path / "vigil.db"
    ledger = CallLedger(db_path=db)
    router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    c = env.client(ledger=ledger)
    for i in range(3):
        c.responses("muse-spark-1.3", {**BODY, "input": f"q{i}"}, purpose="triage")
    c.responses("muse-spark-1.3", {**BODY, "input": "q0"}, purpose="triage")  # cached
    rows = ledger.rows()
    assert len(rows) == 4
    assert ledger.total() == pytest.approx(sum(r.cost_usd for r in rows))
    assert ledger.total() == pytest.approx(3 * SPARK_COST)
    # Persisted in the spec 9.3 model_calls table; a reload agrees.
    with sqlite3.connect(db) as con:
        n, total = con.execute("SELECT COUNT(*), SUM(cost_usd) FROM model_calls").fetchone()
        cached = con.execute("SELECT COUNT(*) FROM model_calls WHERE cached=1").fetchone()[0]
    assert n == 4
    assert cached == 1
    assert total == pytest.approx(ledger.total())
    reloaded = CallLedger(db_path=db)
    assert reloaded.total() == pytest.approx(ledger.total())
    assert len(reloaded.rows()) == 4
    # A guard seeded from the ledger knows the spend.
    assert BudgetGuard(env.settings, spent=reloaded.rows()).spent_total == pytest.approx(
        ledger.total()
    )


# --- budget guard in the client (FR-043) -------------------------------------------------


def test_spend_cap_blocks_live_call_but_cache_continues(env: Env, router):
    route = router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    c = env.client()
    c.responses("muse-spark-1.3", BODY, purpose="triage")
    env.guard.record(139.999, "smoke")
    with pytest.raises(BudgetExceeded) as exc:
        c.responses("muse-spark-1.3", {**BODY, "input": "new"}, purpose="triage")
    assert exc.value.cap == "total"
    assert route.call_count == 1
    # The cached answer is still served.
    assert c.responses("muse-spark-1.3", BODY, purpose="triage")["_vigil"]["cached"] is True
    refused = [r for r in env.ledger.rows() if not r.ok]
    assert len(refused) == 1
    assert "total" in (refused[0].error or "")


def test_window_end_disables_paid_calls(tmp_path: Path, router):
    env = Env(tmp_path, credit_window_end=datetime(2026, 11, 1, tzinfo=UTC))
    route = router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    with pytest.raises(PaidCallsDisabled):
        env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert route.call_count == 0


def _paid_env(tmp_path: Path, **kw) -> Env:
    kw.setdefault("credit_window_end", datetime(2026, 11, 1, tzinfo=UTC))
    kw.setdefault("allow_paid", True)
    return Env(tmp_path, durable=True, **kw)


def test_ledger_rows_are_tagged_credit_inside_the_window(env: Env, router):
    router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    [row] = env.ledger.rows()
    assert row.funding == "credit"
    assert row.feature == "triage"
    assert env.guard.spent_total == pytest.approx(SPARK_COST)
    assert env.guard.spent_paid == 0.0


def test_ledger_rows_are_tagged_paid_after_the_window(tmp_path: Path, router):
    env = _paid_env(tmp_path)
    router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    [row] = env.ledger.rows()
    assert row.funding == "paid"
    assert env.guard.spent_paid == pytest.approx(SPARK_COST)
    assert env.guard.spent_total == 0.0  # paid spend never counts toward the $140


def test_judging_cap_refuses_before_sending(tmp_path: Path, router):
    env = _paid_env(tmp_path)
    route = router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    env.guard.record(24.9999, "sandbox", when=NOW - timedelta(days=1))
    with pytest.raises(BudgetExceeded) as exc:
        env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert exc.value.cap == "judging"
    assert route.call_count == 0
    [row] = env.ledger.rows()
    assert not row.ok
    assert row.funding == "paid"
    assert "judging cap" in (row.error or "")


def test_judging_end_refuses_before_sending(tmp_path: Path, router):
    env = _paid_env(tmp_path, judging_end=NOW - timedelta(minutes=1))
    route = router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    with pytest.raises(BudgetExceeded) as exc:
        env.client().responses("muse-spark-1.3", BODY, purpose="triage")
    assert exc.value.cap == "judging_end"
    assert route.call_count == 0


def test_sqlite_ledger_keeps_funding_and_reseeds_the_guard(tmp_path: Path, router):
    env = _paid_env(tmp_path)
    router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    db = tmp_path / "vigil.db"
    env.client(ledger=CallLedger(db)).responses("muse-spark-1.3", BODY, purpose="triage")
    reopened = CallLedger(db)
    [row] = reopened.rows()
    assert row.funding == "paid"
    assert row.feature == "triage"
    guard = BudgetGuard(env.settings, clock=lambda: NOW, spent=reopened.rows())
    assert guard.spent_paid == pytest.approx(SPARK_COST)
    assert guard.spent_total == 0.0
    reopened.close()


# --- secrets (NFR-014) -------------------------------------------------------------------


def test_api_key_sent_as_bearer_and_never_leaks(env: Env, router, caplog):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(401, json={"error": {"message": f"bad key {KEY}"}})

    router.post("/responses").mock(side_effect=handler)
    c = env.client()
    with pytest.raises(MetaHTTPError) as exc:
        c.responses("muse-spark-1.3", BODY, purpose="triage")
    assert seen["auth"] == f"Bearer {KEY}"
    for text in (repr(c), str(c), str(exc.value), exc.value.body, caplog.text):
        assert KEY not in text
    assert all(KEY not in (r.error or "") for r in env.ledger.rows())


def test_missing_api_key_is_a_clear_error(tmp_path: Path, router):
    env = Env(tmp_path, MODEL_API_KEY=None)
    with pytest.raises(MetaHTTPError, match="MODEL_API_KEY"):
        env.client().responses("muse-spark-1.3", BODY, purpose="triage")


# --- upload and streaming ----------------------------------------------------------------


def test_upload_returns_file_id_and_is_cached(env: Env, router):
    clip = env.tmp_path / "w.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    route = router.post("/files").mock(
        return_value=httpx.Response(200, json={"id": "file-abc", "status": "uploaded"})
    )
    c = env.client()
    assert c.upload(clip) == "file-abc"
    assert c.upload(clip) == "file-abc"
    assert route.call_count == 1
    sent = route.calls[0].request
    assert b'name="purpose"' in sent.content
    assert b"user_data" in sent.content


def test_streamed_response_collects_deltas(env: Env, router):
    events = [
        {"type": "response.created", "response": {"id": "r9", "status": "in_progress"}},
        {"type": "response.output_text.delta", "delta": "line one\n"},
        {"type": "keepalive"},
        {"type": "response.output_text.delta", "delta": "line two\n"},
        {
            "type": "response.completed",
            "response": {"id": "r9", "status": "completed", "usage": OK_BODY["usage"]},
        },
    ]
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    route = router.post("/responses").mock(
        return_value=httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    )
    resp = env.client().responses(
        "sam-3.1", {"input": "x"}, purpose="track", stream=True, units={"frames": 100}
    )
    assert json.loads(route.calls[0].request.content)["stream"] is True
    assert resp["output_text"] == "line one\nline two\n"
    assert resp["deltas"] == ["line one\n", "line two\n"]
    assert resp["id"] == "r9"
    [row] = env.ledger.rows()
    assert row.units == 100
    assert row.cost_usd == pytest.approx(0.02)


def test_stream_without_completion_is_malformed(env: Env, router):
    sse = 'data: {"type": "response.output_text.delta", "delta": "x"}\n\n'
    router.post("/responses").mock(
        return_value=httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    )
    with pytest.raises(MalformedResponse):
        env.client().responses("sam-3.1", {"input": "x"}, purpose="track", stream=True)


# --- Glimmer (FR-028): local llama.cpp, falls back to Spark ------------------------------

GLIMMER = "http://127.0.0.1:8080"


def _summary(**kw) -> VisitSummary:
    base = dict(
        visit_id="v1",
        cameras=["front"],
        event_types=["enter", "exit"],
        rule_fired=False,
        protected_touched=False,
        unresolved_gap=False,
        duration_s=12.0,
    )
    return VisitSummary(**{**base, **kw})


def test_glimmer_triage_parses_decision(env: Env):
    from vigil.meta.glimmer import triage_glimmer

    content = json.dumps({"escalate": True, "reason": "a person stayed by the porch"})
    with respx.mock(base_url=GLIMMER) as r:
        route = r.post("/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
            )
        )
        decision = triage_glimmer(_summary(), url=GLIMMER, ledger=env.ledger)
    sent = json.loads(route.calls[0].request.content)
    assert sent["response_format"]["type"] == "json_schema"
    assert decision.escalate is True
    assert decision.source == "glimmer"
    assert not decision.forced
    [row] = env.ledger.rows()
    assert row.backend == "local"
    assert row.cost_usd == 0


def test_glimmer_unreachable_raises_for_spark_fallback():
    from vigil.meta.glimmer import GlimmerUnavailable, triage_glimmer

    with respx.mock(base_url=GLIMMER) as r:
        r.post("/v1/chat/completions").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(GlimmerUnavailable) as exc:
            triage_glimmer(_summary(), url=GLIMMER)
    assert exc.value.fallback == "spark"


def test_glimmer_garbage_raises_for_spark_fallback():
    from vigil.meta.glimmer import GlimmerUnavailable, triage_glimmer

    with respx.mock(base_url=GLIMMER) as r:
        r.post("/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {"content": "hm"}}]})
        )
        with pytest.raises(GlimmerUnavailable):
            triage_glimmer(_summary(), url=GLIMMER)


# --- Voice Transcribe (FR-022): limits before sending ------------------------------------


def _wav(path: Path, seconds: float, rate: int = 16_000) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))
    return path


def test_asr_rejects_long_or_large_audio_before_sending(env: Env, router):
    from vigil.meta.asr import AudioTooLarge, AudioTooLong, transcribe

    route = router.post("/asr/transcribe").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AudioTooLong):
        transcribe(env.client(), _wav(env.tmp_path / "long.wav", 31))
    with pytest.raises(AudioTooLarge):
        # 20 s at 64 kHz 16-bit mono is about 2.4 MB.
        transcribe(env.client(), _wav(env.tmp_path / "big.wav", 20, rate=64_000))
    assert route.call_count == 0


def test_asr_transcribe_request_shape(env: Env, router):
    from vigil.meta.asr import transcribe

    route = router.post("/asr/transcribe").mock(
        return_value=httpx.Response(200, json={"transcript": "tell me if anyone opens the gate"})
    )
    text = transcribe(env.client(), _wav(env.tmp_path / "ok.wav", 4))
    assert text == "tell me if anyone opens the gate"
    sent = route.calls[0].request.content
    assert b'name="request"' in sent
    assert b"muse-voice-transcribe-1.0" in sent
    assert b'name="audio"' in sent
    [row] = env.ledger.rows()
    assert row.model == "muse-voice-transcribe-1.0"
    assert row.units == 4
    assert row.cost_usd == pytest.approx(4 / 3600 * 0.18)


def test_ledger_behaves_like_a_list_of_rows(env: Env, router):
    router.post("/responses").mock(return_value=httpx.Response(200, json=OK_BODY))
    c = env.client()
    before = len(env.ledger)
    c.responses("muse-spark-1.3", BODY, purpose="triage")
    assert len(env.ledger) == before + 1
    assert env.ledger.since(before) == [env.ledger[-1]]
    assert [r.id for r in env.ledger] == [r.id for r in env.ledger.rows()]
