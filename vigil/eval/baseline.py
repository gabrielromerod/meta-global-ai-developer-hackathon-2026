"""Naive baseline: one Muse Spark call per motion window, "is anything wrong?" (FR-025).

The harness is offline: answers are injected (`answer(window) -> dict`), recorded from a
live run or written by hand for tests. Each answer has the shape

    {"anything_wrong": bool, "claims": [{"text": str, "supported": bool | None}]}

Counting:
- **alert**: a window whose answer says `anything_wrong: true`;
- **unsupported claim**: a claim a reviewer marked `supported: false`, or, when not
  reviewed (`supported` absent or null), a claim made about a window that overlaps no
  labelled subject appearance or labelled event on that camera (auto-judged, and counted
  separately so the reader can see how many claims were judged automatically);
- **error**: an answer that does not have the shape above (not counted as an alert).

The live path (`spark_answer_fn`) needs MODEL_API_KEY, credits and the budget-guarded
MetaClient; without them it raises `BaselineBlocked` with the reason.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from vigil.eval.metrics import ScenarioLabel
from vigil.models import Window

BASELINE_MODEL = "muse-spark-1.3"
BASELINE_PROMPT = (
    "You are watching a 10-second home security camera clip. Is anything wrong? "
    'Answer only JSON: {"anything_wrong": true|false, "claims": [{"text": "..."}]}.'
)

Answer = Callable[[Window], dict]


class BaselineBlocked(RuntimeError):
    """The live baseline cannot run here (no key, no credits, or no MetaClient)."""


def _windows_with_evidence(labels: list[dict] | None) -> list[tuple[str, float, float]]:
    spans: list[tuple[str, float, float]] = []
    for raw in labels or []:
        lab = ScenarioLabel.model_validate({k: v for k, v in raw.items() if not k.startswith("$")})
        for subj in lab.subjects:
            spans.extend((ap.camera_id, ap.t0, ap.t1) for ap in subj.appearances)
        spans.extend((ev.camera_id, ev.t, ev.t) for ev in lab.events)
    return spans


def _supported(w: Window, spans: list[tuple[str, float, float]]) -> bool:
    return any(cam == w.camera_id and t0 <= w.t1 and t1 >= w.t0 for cam, t0, t1 in spans)


def _valid(answer: Any) -> bool:
    return (
        isinstance(answer, dict)
        and isinstance(answer.get("anything_wrong"), bool)
        and isinstance(answer.get("claims", []), list)
    )


def run_baseline(
    windows: list[Window],
    answer: Answer | None = None,
    labels: list[dict] | None = None,
) -> dict:
    """Count baseline alerts and unsupported claims over motion windows (FR-025)."""
    if answer is None:
        answer = spark_answer_fn()
    spans = _windows_with_evidence(labels)
    per_window: list[dict] = []
    alerts = claims = unsupported = auto = errors = 0
    for w in sorted(windows, key=lambda w: (w.camera_id, w.t0, w.id)):
        try:
            a = answer(w)
        except BaselineBlocked:
            raise
        except Exception as err:  # a failed call is an error, never a silent "no alert"
            a = {"error": f"{type(err).__name__}: {err}"}
        if not _valid(a):
            errors += 1
            per_window.append({"window_id": w.id, "camera_id": w.camera_id, "error": True})
            continue
        wrong = bool(a["anything_wrong"])
        alerts += int(wrong)
        w_unsupported = 0
        for c in a.get("claims", []):
            claims += 1
            flag = c.get("supported") if isinstance(c, dict) else None
            if flag is None:
                auto += 1
                flag = _supported(w, spans) if labels else None
            if flag is False:
                w_unsupported += 1
        unsupported += w_unsupported
        per_window.append(
            {
                "window_id": w.id,
                "camera_id": w.camera_id,
                "t0": w.t0,
                "t1": w.t1,
                "alert": wrong,
                "claims": len(a.get("claims", [])),
                "unsupported": w_unsupported,
            }
        )
    return {
        "model": BASELINE_MODEL,
        "windows": len(windows),
        "alerts": alerts,
        "claims": claims,
        "unsupported_claims": unsupported,
        "auto_judged_claims": auto,
        "errors": errors,
        "per_window": per_window,
    }


def side_by_side(baseline_report: dict, vigil_metrics: dict) -> dict:
    """The FR-025 comparison table: naive baseline versus Vigil on the same scenarios."""
    t = vigil_metrics["totals"]
    return {
        "baseline": {
            "alerts": baseline_report["alerts"],
            "unsupported_claims": baseline_report["unsupported_claims"],
            "calls": baseline_report["windows"],
        },
        "vigil": {
            "alerts": t["alerts"],
            "unsupported_claims": t["claims_inside_gaps"] + t["uncited_sentences_shipped"],
            "motion_triggers": t["motion_triggers"],
        },
    }


def spark_answer_fn(client: Any | None = None) -> Answer:
    """Live answer function through MetaClient (budget guard, cache, ledger).

    Raises `BaselineBlocked` when no API key is configured or MetaClient is not ready.
    """
    if client is None:
        if not os.environ.get("MODEL_API_KEY"):
            raise BaselineBlocked(
                "blocked: FR-025 live baseline needs MODEL_API_KEY and Meta API credits; "
                "pass recorded answers to run_baseline() instead"
            )
        try:
            from vigil.meta.client import MetaClient

            client = MetaClient()
        except Exception as err:
            raise BaselineBlocked(f"blocked: MetaClient unavailable ({err})") from err

    def answer(w: Window) -> dict:
        if not w.path:
            raise ValueError(f"window {w.id} has no clip path")
        from pathlib import Path

        try:
            file_id = w.file_id or client.upload(Path(w.path))
            body = {
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": BASELINE_PROMPT},
                            {"type": "input_video", "file_id": file_id},
                        ],
                    }
                ]
            }
            raw = client.responses(BASELINE_MODEL, body, purpose="baseline")
        except NotImplementedError as err:
            raise BaselineBlocked(f"blocked: MetaClient not implemented yet ({err})") from err
        return _parse_answer(raw)

    return answer


def _parse_answer(raw: Any) -> dict:
    """Best-effort extraction of the JSON answer from a Responses API payload."""
    if isinstance(raw, dict) and "anything_wrong" in raw:
        return raw
    text = None
    if isinstance(raw, dict):
        text = raw.get("output_text")
        if text is None:
            for item in raw.get("output") or []:
                for part in item.get("content") or []:
                    if isinstance(part, dict) and part.get("text"):
                        text = part["text"]
    elif hasattr(raw, "text"):
        text = raw.text
    try:
        return json.loads(text) if text else {"error": "empty"}
    except (TypeError, json.JSONDecodeError):
        return {"error": "malformed"}
