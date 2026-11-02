"""Muse Glimmer 30B triage through a local llama.cpp server (FR-028).

The llama.cpp server exposes an OpenAI-compatible ``POST /v1/chat/completions`` that
accepts ``response_format: {"type": "json_schema", ...}``. Glimmer runs on the owner's
RTX 3090 (gate H-03), never billed by Meta, so ledger rows have ``backend="local"`` and
cost 0. If the server is unreachable or answers garbage, :class:`GlimmerUnavailable` is
raised and the caller falls back to Spark (``vigil.meta.spark.triage``).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime

import httpx

from vigil.meta.cache import request_hash
from vigil.meta.prompts import load_prompt
from vigil.models import ModelCall, TriageDecision, VisitSummary
from vigil.settings import get_settings

GLIMMER_MODEL = "muse-glimmer-30b-q4"
"""Label for the local GGUF in the ledger (not a Meta API model ID)."""

TRIAGE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["escalate", "reason"],
    "properties": {
        "escalate": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 200},
    },
}


class GlimmerUnavailable(RuntimeError):
    """Local triage failed; use Spark instead (FR-028)."""

    fallback = "spark"


def build_request(summary: VisitSummary) -> dict:
    prompt = load_prompt("triage")
    return {
        "model": GLIMMER_MODEL,
        "temperature": 0,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": prompt.text},
            {"role": "user", "content": summary.model_dump_json()},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "triage", "schema": TRIAGE_SCHEMA, "strict": True},
        },
    }


def parse_decision(data: dict) -> TriageDecision:
    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        escalate = parsed["escalate"]
        reason = str(parsed["reason"])[:200]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GlimmerUnavailable(f"unreadable Glimmer answer: {type(exc).__name__}") from None
    if not isinstance(escalate, bool):
        raise GlimmerUnavailable("Glimmer answer: escalate is not a boolean")
    return TriageDecision(escalate=escalate, forced=False, reason=reason, source="glimmer")


def triage_glimmer(
    summary: VisitSummary,
    *,
    url: str | None = None,
    transport: httpx.BaseTransport | None = None,
    ledger=None,
    timeout_s: float = 30.0,
) -> TriageDecision:
    """Ask local Glimmer whether to escalate; raise GlimmerUnavailable on any failure."""
    base = (url or get_settings().glimmer_url).rstrip("/")
    body = build_request(summary)
    t0 = time.perf_counter()
    error: str | None = None
    decision: TriageDecision | None = None
    try:
        with httpx.Client(base_url=base, transport=transport, timeout=timeout_s) as http:
            resp = http.post("/v1/chat/completions", json=body)
        if resp.status_code >= 400:
            raise GlimmerUnavailable(f"Glimmer HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError:
            raise GlimmerUnavailable("Glimmer response is not JSON") from None
        decision = parse_decision(data)
        return decision
    except httpx.HTTPError as exc:
        error = f"Glimmer unreachable: {type(exc).__name__}"
        raise GlimmerUnavailable(error) from None
    except GlimmerUnavailable as exc:
        error = str(exc)
        raise
    finally:
        if ledger is not None:
            ledger.add(
                ModelCall(
                    id="mc_" + uuid.uuid4().hex[:16],
                    model=GLIMMER_MODEL,
                    purpose="triage",
                    visit_id=summary.visit_id,
                    req_hash=request_hash(GLIMMER_MODEL, body),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    cost_usd=0.0,
                    ok=decision is not None,
                    error=error,
                    backend="local",
                    created_at=datetime.now(UTC),
                ),
                "triage",
            )
