---
name: meta-fixture
description: Use when a test needs a Meta Model API response (SAM 3.1, Muse Spark, Muse Wonder, Voice Transcribe), when recording or refreshing fixtures under tests/fixtures/meta/, when running scripts/smoke_meta.py, or when replaying responses with respx or a fake MetaClient in pytest.
---

# Meta fixtures: record once, replay forever

## Overview

CI and every default test run use **recorded** Meta responses only. Recording is a billed,
owner-approved event; replay is free and deterministic. Never hand-invent a "real" response
and label it recorded.

## Recording (rare, billed, owner only)

Preconditions, all required:
1. The owner explicitly approved this recording in this session (scope: which models, how many calls).
2. The `budget-check` skill was run and the estimate fits the caps and the credit window.
3. `MODEL_API_KEY` is set in `.env` by the owner. You never paste or echo it.

Command (the only sanctioned path; it goes through `MetaClient` and the budget guard):
```bash
uv run python scripts/smoke_meta.py --live --record
```
Run `uv run python scripts/smoke_meta.py --help` first to see current flags. Without
`--live` it must not touch the network.

Store results under `tests/fixtures/meta/recorded/`, one file per call, named
`<model>__<purpose>__<short-hash>.json` (or the layout `smoke_meta.py` writes).

## Scrub before saving (mandatory)

- Remove `Authorization` headers, API keys, cookies, account/org/project IDs, request IDs
  that link to the account, and signed URLs. Replace `file_id`s with stable fakes (`file_test_001`).
- No pixels from real footage: keep masks/RLE only for synthetic or masked demo windows.
- Check model IDs: **never a `-contributor` ID** (CI fails on it; `ModelCall` rejects it).
- Verify: `grep -rniE "bearer|api[_-]?key|authorization|-contributor" tests/fixtures/meta/`
  returns nothing.
- Record the date, model ID and smoke-test cost in the commit message or `eval/budget.md`.

## Replay in tests

Mock the HTTP layer with respx so `MetaClient` (retries, cache, ledger) is still exercised:

```python
import json, httpx, respx
from pathlib import Path

REC = Path(__file__).parents[1] / "fixtures" / "meta" / "recorded"


@respx.mock
def test_sam_parse_empty(tmp_path):
    body = json.loads((REC / "sam-3.1__track__empty.json").read_text(encoding="utf-8"))
    respx.post(url__regex=r".*/v1/responses$").mock(return_value=httpx.Response(200, json=body))
    ...  # call vigil.meta.sam.track_concept(client, window, "person") -> []
```

- Faults (`test_client_retry`, `test_client_faults.py`): `side_effect=[httpx.Response(429), httpx.Response(500), httpx.Response(200, json=body)]`, and `httpx.ReadTimeout`.
- Pure logic tests (validator, verdict, visits) should use a fake client or plain dicts
  instead of HTTP; respx belongs at the `MetaClient` boundary.
- Hand-written fixtures for edge cases (malformed JSON, 400 body, 17 objects) live in
  `tests/fixtures/meta/` (not `recorded/`) and say so in the file name, e.g. `synthetic_`.
- Point the client at a temp cache (`tmp_path`) so tests never share `.vigil-cache/`.

## Red flags

- A test that passes only with `MODEL_API_KEY` set, or hits `api.meta.ai`.
- Calling `httpx` directly to Meta instead of through `MetaClient`.
- Re-recording "just to refresh" without approval and a budget check.
- Unscrubbed headers or IDs in a fixture diff.
