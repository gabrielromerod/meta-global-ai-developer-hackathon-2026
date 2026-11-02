"""T-03 Meta smoke test: one call per model, behind --live and MODEL_API_KEY.

    uv run python scripts/smoke_meta.py              # print the plan, make no call, exit 0
    uv run python scripts/smoke_meta.py --live       # one real call per model (about $1)
    uv run python scripts/smoke_meta.py --live --record   # also save raw responses to
                                                          # tests/fixtures/meta/recorded/

Every call goes through vigil.meta.client.MetaClient (retries, cache, budget guard,
ledger). If MetaClient is not importable or not implemented yet, the live run stops with
a clear "blocked" message instead of calling the API directly.

Only the four Standard-mode model IDs are allowed; any `-contributor` ID is refused
(NFR-004, spec 11.6 safeguard 5). Request shapes follow
https://dev.meta.ai/docs/sam/segmenting (POST /v1/responses, `input` message with
`input_text` / `input_image`, `metadata.include_confidence` as the string "true").
The Voice Transcribe request shape is unverified (spec 5.14 open question 2).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import struct
import sys
import time
import wave
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RECORD_DIR = REPO / "tests" / "fixtures" / "meta" / "recorded"

ALLOWED = ("sam-3.1", "muse-spark-1.3", "muse-wonder-1.0", "muse-voice-transcribe-1.0")

PLAN = {
    "sam-3.1": ("point prompt on a 64x36 synthetic image (FR-019)", 0.0025),
    "muse-spark-1.3": ("strict-JSON text reply (FR-021, open question 3 needs video)", 0.001),
    "muse-wonder-1.0": ("strict JSON schema story stub (open question 1)", 0.005),
    "muse-voice-transcribe-1.0": ("1 s of silence, batch transcribe (open question 2)", 0.0001),
}


def _png(width: int = 64, height: int = 36) -> bytes:
    """A synthetic grey image with a white box: no camera content."""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            v = 255 if 20 <= x < 44 and 10 <= y < 26 else 96
            row += bytes([v, v, v])
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def _silence_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def request_body(model: str) -> dict:
    if model == "sam-3.1":
        img = "data:image/png;base64," + base64.b64encode(_png()).decode()
        return {
            "model": model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "<0f>1<|point;x=32;y=18;w=64;h=36|>"},
                        {"type": "input_image", "image_url": img},
                    ],
                }
            ],
            "metadata": {"include_confidence": "true"},
            "stream": True,
        }
    if model in ("muse-spark-1.3", "muse-wonder-1.0"):
        return {
            "model": model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": 'Reply with exactly this JSON and nothing else: {"ok": true}',
                        }
                    ],
                }
            ],
        }
    if model == "muse-voice-transcribe-1.0":
        return {
            "model": model,
            "audio_b64": base64.b64encode(_silence_wav()).decode(),
            "format": "wav",
        }
    raise ValueError(model)


def check_model_id(model: str) -> str | None:
    """Return a refusal reason, or None when the ID is allowed."""
    if "-contributor" in model:
        return f"refused: {model!r} is a Contributor-mode ID (content used for training, NFR-004)"
    if model not in ALLOWED:
        return f"refused: {model!r} is not one of the Standard-mode IDs {', '.join(ALLOWED)}"
    return None


def record_path(
    model: str, record: bool, root: Path = RECORD_DIR, digest: str = "0000000"
) -> Path | None:
    """Where a scrubbed response is saved (`<model>__smoke__<hash>.json`): only with --record."""
    return Path(root) / f"{model}__smoke__{digest[:7]}.json" if record else None


_SCRUB_KEYS = (
    "authorization", "api_key", "apikey", "cookie", "org", "organization", "project",
    "account", "request_id", "x-request-id", "user",
)  # fmt: skip


def scrub(obj: object, _ids: dict[str, str] | None = None) -> object:
    """Drop credential/account keys and replace file ids with stable fakes (meta-fixture)."""
    ids = {} if _ids is None else _ids
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(kl == s or kl.endswith("_" + s) for s in _SCRUB_KEYS):
                continue
            if kl == "file_id" and isinstance(v, str):
                out[k] = ids.setdefault(v, f"file_test_{len(ids) + 1:03d}")
            else:
                out[k] = scrub(v, ids)
        return out
    if isinstance(obj, list):
        return [scrub(v, ids) for v in obj]
    if isinstance(obj, str) and obj.lower().startswith("bearer "):
        return "Bearer ***"
    return obj


def _api_key() -> str:
    if "MODEL_API_KEY" in os.environ:  # explicit env wins, even when empty
        return os.environ["MODEL_API_KEY"].strip()
    try:
        from vigil.settings import get_settings

        key = get_settings().model_api_key
        return key.get_secret_value().strip() if key else ""
    except Exception:
        return ""


def _jsonable(raw: object) -> object:
    if hasattr(raw, "model_dump"):
        return raw.model_dump(mode="json")
    if isinstance(raw, dict | list | str | int | float | bool) or raw is None:
        return raw
    return {"repr": repr(raw)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--live", action="store_true", help="make one real, billed call per model")
    ap.add_argument("--record", action="store_true", help="save raw responses as fixtures")
    ap.add_argument("--model", action="append", help="limit to these model IDs (repeatable)")
    args = ap.parse_args(argv)

    models = args.model or list(ALLOWED)
    for m in models:
        reason = check_model_id(m)
        if reason:
            print(reason, file=sys.stderr)
            return 2

    total = sum(PLAN[m][1] for m in models)
    print("Meta smoke test (T-03)")
    for m in models:
        what, usd = PLAN[m]
        print(f"  {m:<28} {what}  ~${usd:.4f}")
    print(f"  estimated total ~${total:.4f}")
    if not args.live:
        print("Plan only: no call made. Pass --live (with MODEL_API_KEY) to run it.")
        return 0

    if not _api_key():
        print("blocked: MODEL_API_KEY is not set; no call made.", file=sys.stderr)
        return 3
    try:
        from vigil.meta.client import MetaClient

        client = MetaClient()
    except Exception as err:
        print(
            f"blocked: vigil.meta.client.MetaClient is not available ({type(err).__name__}: "
            f"{err}); refusing to call the API without the budget guard.",
            file=sys.stderr,
        )
        return 3

    failures = 0
    for m in models:
        body = request_body(m)
        started = time.perf_counter()
        try:
            if m == "muse-voice-transcribe-1.0":
                transcribe = getattr(client, "transcribe", None)
                if transcribe is None:
                    raise NotImplementedError("MetaClient has no transcribe() yet")
                raw = transcribe(_silence_wav(), purpose="smoke")
            else:
                payload = {k: v for k, v in body.items() if k != "model"}
                raw = client.responses(m, payload, purpose="smoke", stream=bool(body.get("stream")))
        except NotImplementedError as err:
            print(f"  {m}: blocked: {err}", file=sys.stderr)
            failures += 1
            continue
        except Exception as err:
            print(f"  {m}: FAILED {type(err).__name__}: {err}", file=sys.stderr)
            failures += 1
            continue
        ms = int(1000 * (time.perf_counter() - started))
        print(f"  {m}: ok in {ms} ms")
        text = json.dumps(scrub(_jsonable(raw)), indent=2, sort_keys=True) + "\n"
        path = record_path(m, args.record, digest=hashlib.sha256(text.encode()).hexdigest())
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"    recorded -> {path.relative_to(REPO)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
