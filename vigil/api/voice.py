"""Voice rules over HTTP: fixtures and transcription (FR-022, NFR-002, NFR-015; spec 9.6).

`POST /api/voice/transcribe` takes either a 16 kHz mono 16-bit PCM WAV recorded and encoded
in the browser (at most 30 s and 2 MB; 413 above, 415 for any other format), or the JSON
`{fixture_id, live}` of one of the 3 sample-audio buttons. Live calls pass the same guards as
every other live button and go through the injected backend (`vigil.meta.asr` in production);
the transcript comes back editable, and compiling it is a separate call (FR-021).

Spoken audio stays in memory: it is never written to disk or cached. Only its transcript is
kept, keyed by the audio's SHA-256. The sample buttons send a consented WAV from `demo/voice/`
only when `config/audio_fixtures.json` lists it with a matching SHA-256; until the owner
records them (T-07a) they use the cached transcripts in the bundle (`presets.json`, `voice`).
"""

from __future__ import annotations

import hashlib
import io
import json
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field

from vigil.api.guards import NOTICE_BUDGET, read_bounded
from vigil.api.routes import (
    Runtime,
    _accept_live,
    _envelope,
    _failed_notice,
    _failure,
    _live_gate,
    _parse,
    _Req,
    _state,
    _telemetry_cached,
    _telemetry_live,
)

WAV_TYPES = {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"}
NOTICE_NOT_RECORDED = "This sample's audio is not in this build yet; recorded result shown"
NOTICE_TYPE = "type the rule instead"
NOTE_PENDING = (
    "Sample audio: the 3 consented recordings are made by the owner in T-07a. Until then each "
    "button uses its cached transcript, labelled as a recorded result."
)
NOTE_RECORDED = (
    "Sample audio: consented recordings listed by SHA-256 in config/audio_fixtures.json; "
    "each falls back to its cached transcript."
)


class TranscribeFixtureRequest(_Req):
    fixture_id: str = Field(min_length=1, max_length=64)
    live: bool = False


# ---------------------------------------------------------------------------
# Fixtures: bundle presets (cached transcripts) + config allowlist (consented WAVs)
# ---------------------------------------------------------------------------


def _allowlist(path: Path | None) -> dict[str, dict[str, Any]]:
    """config/audio_fixtures.json entries by id; a missing or broken file lists nothing."""
    if path is None:
        return {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = raw.get("fixtures", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return {}
    return {str(e["id"]): e for e in items if isinstance(e, dict) and "id" in e and "sha256" in e}


def fixture_audio(request: Request, fixture_id: str) -> bytes | None:
    """The consented WAV for a fixture, only if listed and its SHA-256 matches (NFR-002)."""
    state = request.app.state
    entry = _allowlist(state.audio_fixtures_path).get(fixture_id)
    root = state.voice_dir
    if entry is None or root is None or not entry.get("file"):
        return None
    base = Path(root).resolve()
    path = (base / str(entry["file"])).resolve()
    if base not in path.parents or not path.is_file():
        return None
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        return None
    return data


def fixtures(request: Request) -> list[dict[str, Any]]:
    """Every fixture: bundle presets first (they carry the recorded call), then config-only."""
    bundle = request.app.state.bundle
    allow = _allowlist(request.app.state.audio_fixtures_path)
    out: list[dict[str, Any]] = []
    for p in bundle.presets.get("voice", []):
        cached = p.get("transcript") or allow.get(p["id"], {}).get("transcript")
        out.append({**p, "transcript": cached})
    seen = {f["id"] for f in out}
    for fid, e in allow.items():
        if fid not in seen:
            out.append(
                {
                    "id": fid,
                    "label": e.get("label") or fid,
                    "transcript": e.get("transcript"),
                    "model": "muse-voice-transcribe-1.0",
                }
            )
    return out


def _fixture_view(request: Request, f: dict[str, Any]) -> dict[str, Any]:
    recorded = fixture_audio(request, f["id"]) is not None
    return {
        "id": f["id"],
        "label": f.get("label") or f["id"],
        "transcript": f.get("transcript"),
        "seconds": f.get("seconds"),
        "recorded": recorded,
        "wav_url": f"/api/voice/fixtures/{f['id']}/audio" if recorded else None,
    }


# ---------------------------------------------------------------------------
# Audio checks (NFR-015, FR-022): size first, then format, then duration
# ---------------------------------------------------------------------------


def check_wav(audio: bytes, max_s: float, max_bytes: int) -> float:
    """Return the duration; 413 over 2 MB or 30 s, 415 if not 16 kHz mono 16-bit PCM WAV."""
    try:
        from vigil.meta import asr
    except ImportError:  # pragma: no cover - the module is part of the repo
        asr = None  # type: ignore[assignment]
    if asr is not None and hasattr(asr, "validate_wav"):
        try:
            return float(asr.validate_wav(audio, max_s, max_bytes).duration_s)
        except (asr.AudioTooLarge, asr.AudioTooLong) as exc:
            raise HTTPException(413, str(exc)) from exc
        except asr.AudioFormatRejected as exc:
            raise HTTPException(415, str(exc)) from exc
        except asr.AudioRejected as exc:
            raise HTTPException(415, str(exc)) from exc
    if len(audio) > max_bytes:
        raise HTTPException(413, f"Audio over {max_bytes} bytes.")
    try:
        with wave.open(io.BytesIO(audio)) as w:
            ok = (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
            seconds = w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        raise HTTPException(415, "audio must be a 16 kHz mono 16-bit PCM WAV") from exc
    if not ok:
        raise HTTPException(415, "audio must be a 16 kHz mono 16-bit PCM WAV")
    if seconds > max_s:
        raise HTTPException(413, f"Audio over {max_s:.0f} s.")
    return seconds


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def voice_router() -> APIRouter:
    r = APIRouter(prefix="/api/voice")

    @r.get("/fixtures")
    def list_fixtures(request: Request) -> dict[str, Any]:
        items = [_fixture_view(request, f) for f in fixtures(request)]
        pending = any(not f["recorded"] for f in items)
        return {"fixtures": items, "note": NOTE_PENDING if pending else NOTE_RECORDED}

    @r.get("/fixtures/{fixture_id}/audio")
    def fixture_wav(fixture_id: str, request: Request) -> Response:
        data = fixture_audio(request, fixture_id)
        if data is None:
            raise HTTPException(404, f"no consented recording for {fixture_id!r}")
        return Response(data, media_type="audio/wav")

    @r.post("/transcribe")
    async def transcribe(request: Request) -> dict[str, Any]:
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype == "application/json":
            req: TranscribeFixtureRequest = await _parse(request, TranscribeFixtureRequest)
            return _transcribe_fixture(request, req)
        if ctype in WAV_TYPES:
            settings = request.app.state.settings
            audio = await read_bounded(request, int(settings.max_audio_bytes))
            seconds = check_wav(audio, float(settings.max_audio_s), int(settings.max_audio_bytes))
            live = request.query_params.get("live", "").lower() in {"1", "true", "yes"}
            return _transcribe_audio(request, audio, seconds, live)
        raise HTTPException(
            415, "send audio/wav (16 kHz mono 16-bit PCM, at most 30 s and 2 MB) or {fixture_id}"
        )

    return r


def _result(text: str, fixture_id: str | None, sha: str | None, seconds: float | None) -> dict:
    return {"transcript": text, "fixture_id": fixture_id, "editable": True,
            "audio_sha256": sha, "seconds": seconds}  # fmt: skip


def _remember(runtime: Runtime, sha: str, text: str) -> None:
    with runtime.lock:
        runtime.transcripts[sha] = text


def _transcribe_fixture(request: Request, req: TranscribeFixtureRequest) -> dict[str, Any]:
    _, guards, runtime, backend = _state(request)
    fixture = next((f for f in fixtures(request) if f["id"] == req.fixture_id), None)
    if fixture is None:
        raise HTTPException(404, f"unknown voice fixture {req.fixture_id!r}")
    status = _live_gate(request, guards, req.live, "transcribe")
    notice, error = None, None
    if status is not None and status.available:
        wav = fixture_audio(request, req.fixture_id)
        if wav is None:
            notice = NOTICE_NOT_RECORDED
        else:
            sha = hashlib.sha256(wav).hexdigest()
            try:
                res = backend.transcribe(wav, "audio/wav")
                calls = _accept_live(guards, runtime, res)
                text = str(res.payload["transcript"])
                _remember(runtime, sha, text)
                return _envelope(True, True, _result(text, req.fixture_id, sha, None),
                                 _telemetry_live(calls))  # fmt: skip
            except Exception as exc:  # degrade to the cached transcript (NFR-010)
                error = _failure(guards, exc)
                notice = _failed_notice(fixture)
    elif status is not None:
        notice = status.notice
    text = fixture.get("transcript") or ""
    return _envelope(False, req.live, _result(text, req.fixture_id, None, fixture.get("seconds")),
                     _telemetry_cached(fixture), notice, error)  # fmt: skip


def _cached_for_audio(request: Request, runtime: Runtime, sha: str) -> dict[str, Any] | None:
    """A transcript already known for these exact bytes: this session, or a listed fixture."""
    with runtime.lock:
        if sha in runtime.transcripts:
            return {"transcript": runtime.transcripts[sha]}
    allow = _allowlist(request.app.state.audio_fixtures_path)
    for f in fixtures(request):
        if allow.get(f["id"], {}).get("sha256") == sha and f.get("transcript"):
            return f
    return None


def _transcribe_audio(request: Request, audio: bytes, seconds: float, live: bool) -> dict:
    _, guards, runtime, backend = _state(request)
    sha = hashlib.sha256(audio).hexdigest()
    status = _live_gate(request, guards, live, "transcribe")
    notice, error = None, None
    if status is not None and status.available:
        try:
            res = backend.transcribe(audio, "audio/wav")
            calls = _accept_live(guards, runtime, res)
            text = str(res.payload["transcript"])
            _remember(runtime, sha, text)
            return _envelope(True, True, _result(text, None, sha, seconds),
                             _telemetry_live(calls))  # fmt: skip
        except Exception as exc:
            error = _failure(guards, exc)
    cached = _cached_for_audio(request, runtime, sha)
    if cached is not None:
        if error:
            notice = _failed_notice(cached)
        elif status is not None:
            notice = status.notice
        return _envelope(False, live, _result(cached["transcript"], cached.get("id"), sha, seconds),
                         _telemetry_cached(cached), notice, error)  # fmt: skip
    # Nothing recorded for this recording: an empty, editable transcript plus typing (UC-03).
    if error:
        notice = f"Live call failed; no recorded transcript for this recording, so {NOTICE_TYPE}"
    elif status is None:
        notice = f"Live transcription was not requested; {NOTICE_TYPE}"
    elif status.notice == NOTICE_BUDGET:
        notice = f"{NOTICE_BUDGET}. No recorded transcript for this recording, so {NOTICE_TYPE}"
    else:
        notice = f"{status.notice}. No recorded transcript for this recording, so {NOTICE_TYPE}"
    return _envelope(False, live, _result("", None, sha, seconds), _telemetry_cached(None),
                     notice, error)  # fmt: skip
