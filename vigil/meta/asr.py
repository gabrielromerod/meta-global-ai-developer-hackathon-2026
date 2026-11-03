"""Muse Voice Transcribe for voice rules (FR-022, P0; NFR-002, NFR-015).

Endpoint per https://dev.meta.ai/docs/api-reference/voice/transcribe (read 2026-11-02):
batch ``POST /v1/asr/transcribe``, ``multipart/form-data`` with a ``request`` JSON part
(``model``, ``audioEncoding: "WAV"``, ``mode: "PUSH_TO_TALK"``) and an ``audio`` part.
:data:`ENDPOINT_CONFIRMED` stays ``False`` until the T-03 smoke test proves the request
fields (spec 5.14 item 2); if batch fails there, FR-022 falls back to the 3 fixture buttons on
cached transcripts and typing.

Input contract (FR-022): the browser records up to 30 s, downsamples to 16 kHz mono and
encodes 16-bit PCM WAV (30 s is about 0.96 MB). :func:`validate_wav` parses the RIFF header
and enforces exactly that, plus Vigil's own limits (30 s and 2 MB, NFR-015), before anything
is sent.

Privacy (NFR-002): audio is handled as bytes in memory. It is sent only to Voice Transcribe
and is never written to disk or to the response cache; only the transcript is cached, keyed
by the audio's SHA-256 (:func:`transcript_cache_key`). The 3 consented fixtures under
``demo/voice/`` are listed by SHA-256 in ``config/audio_fixtures.json`` with their cached
transcripts, so the fixture buttons work offline (:func:`transcribe_fixture`).

The ``TranscribeResponse`` body is not documented in detail, so the parser accepts
``transcript`` / ``text`` or a list of turns; an unrecognised body raises
:class:`TranscriptUnrecognised` (verify with the T-03 smoke test).
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from vigil.meta.budget import VOICE, BudgetExceeded
from vigil.meta.client import MetaError
from vigil.settings import REPO_ROOT

TRANSCRIBE_PATH = "/asr/transcribe"
REQUEST: dict[str, str] = {"model": VOICE, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
ENDPOINT_CONFIRMED = False
"""Set to True only after the T-03 live smoke test confirms the batch request fields."""
PURPOSE = "voice_rule_transcribe"

MAX_AUDIO_S = 30
MAX_AUDIO_BYTES = 2 * 1024 * 1024
SAMPLE_RATE = 16_000
CHANNELS = 1
BITS_PER_SAMPLE = 16
_WAVE_FORMAT_PCM = 0x0001
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE

FIXTURES_PATH = REPO_ROOT / "config" / "audio_fixtures.json"
FIXTURE_ROOT = REPO_ROOT / "demo" / "voice"

TranscriptSource = Literal["live", "cache", "fixture"]


class AudioRejected(ValueError):
    """Audio refused before sending (maps to HTTP 413/400 at the API layer)."""


class AudioTooLong(AudioRejected):
    pass


class AudioTooLarge(AudioRejected):
    pass


class AudioFormatRejected(AudioRejected):
    """A WAV, but not 16 kHz mono 16-bit PCM (FR-022)."""


class TranscriptUnrecognised(RuntimeError):
    """The transcribe response had no transcript Vigil could read."""


class TranscriptUnavailable(LookupError):
    """No live call was possible and no cached transcript exists for this audio."""


# ---------------------------------------------------------------------------
# WAV validation (parse the header; nothing is decoded or stored)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WavInfo:
    sample_rate: int
    channels: int
    bits_per_sample: int
    data_bytes: int
    duration_s: float


def validate_wav(
    data: bytes, max_s: float = MAX_AUDIO_S, max_bytes: int = MAX_AUDIO_BYTES
) -> WavInfo:
    """Check size, RIFF/WAVE header, 16 kHz mono 16-bit PCM and duration, in that order.

    The duration comes from the bytes actually present in the ``data`` chunk, so a header
    that claims more (a streaming-style size) cannot under- or over-state it.
    """
    size = len(data)
    if size > max_bytes:
        raise AudioTooLarge(f"audio is {size} bytes; the limit is {max_bytes} bytes")
    if size < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise AudioRejected("audio must be a RIFF/WAVE file (16 kHz mono 16-bit PCM)")
    fmt: tuple[int, ...] | None = None
    fmt_ext_sub: int | None = None
    data_len: int | None = None
    pos = 12
    while pos + 8 <= size:
        chunk_id = data[pos : pos + 4]
        (chunk_size,) = struct.unpack_from("<I", data, pos + 4)
        body = pos + 8
        if chunk_id == b"fmt ":
            if chunk_size < 16 or body + 16 > size:
                raise AudioRejected("WAV fmt chunk is truncated")
            fmt = struct.unpack_from("<HHIIHH", data, body)
            if fmt[0] == _WAVE_FORMAT_EXTENSIBLE and chunk_size >= 40 and body + 26 <= size:
                (fmt_ext_sub,) = struct.unpack_from("<H", data, body + 24)
        elif chunk_id == b"data" and data_len is None:
            data_len = max(0, min(chunk_size, size - body))
        pos = body + chunk_size + (chunk_size & 1)
    if fmt is None:
        raise AudioRejected("WAV has no fmt chunk")
    if data_len is None:
        raise AudioRejected("WAV has no data chunk")
    code, channels, rate, _byte_rate, _align, bits = fmt
    if code == _WAVE_FORMAT_EXTENSIBLE:
        code = fmt_ext_sub if fmt_ext_sub is not None else code
    if code != _WAVE_FORMAT_PCM:
        raise AudioFormatRejected(f"audio must be linear PCM (WAV format 1), got format {code}")
    if channels != CHANNELS:
        raise AudioFormatRejected(f"audio must be mono, got {channels} channels")
    if rate != SAMPLE_RATE:
        raise AudioFormatRejected(f"audio must be sampled at {SAMPLE_RATE} Hz, got {rate} Hz")
    if bits != BITS_PER_SAMPLE:
        raise AudioFormatRejected(f"audio must be 16-bit PCM, got {bits}-bit")
    duration = data_len / float(rate * channels * bits // 8)
    if duration > max_s + 1e-9:
        raise AudioTooLong(f"audio is {duration:.1f} s; the limit is {max_s:.0f} s")
    return WavInfo(rate, channels, bits, data_len, duration)


def check_audio(audio: Path | bytes, max_s: float, max_bytes: int) -> float:
    """Enforce the FR-022 format and the 30 s / 2 MB limits; return the duration in seconds."""
    return validate_wav(_audio_bytes(audio), max_s, max_bytes).duration_s


def wav_duration_s(audio: Path | bytes) -> float:
    return validate_wav(_audio_bytes(audio), float("inf"), 1 << 62).duration_s


def _audio_bytes(audio: Path | bytes | bytearray | memoryview) -> bytes:
    if isinstance(audio, bytes | bytearray | memoryview):
        return bytes(audio)
    return Path(audio).read_bytes()


# ---------------------------------------------------------------------------
# Request and response
# ---------------------------------------------------------------------------


def audio_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def transcript_cache_key(sha256: str) -> str:
    """Response-cache key of a transcript: the audio's SHA-256 (NFR-002)."""
    return f"asr-{sha256}"


def build_transcribe_request(
    data: bytes,
) -> tuple[dict[str, str], dict[str, tuple[str, bytes, str]]]:
    """The batch request: a ``request`` JSON part and an in-memory ``audio`` part.

    The part's file name is fixed, so the uploader's own file name never leaves the house.
    """
    return dict(REQUEST), {"audio": ("rule.wav", data, "audio/wav")}


def parse_transcript(data: dict[str, Any]) -> str:
    for key in ("transcript", "text"):
        if isinstance(data.get(key), str):
            return data[key].strip()
    for key in ("turns", "results", "segments", "transcripts"):
        items = data.get(key)
        if isinstance(items, list):
            texts = [
                str(i.get("transcript") or i.get("text") or "").strip()
                for i in items
                if isinstance(i, dict)
            ]
            if any(texts):
                return " ".join(t for t in texts if t)
    keys = sorted(k for k in data if k != "_vigil")[:10]
    raise TranscriptUnrecognised(f"no transcript in response keys {keys}")


def _transcript_only(data: dict[str, Any]) -> dict[str, str]:
    """What the response cache may keep: the transcript and nothing else (NFR-002)."""
    return {"transcript": parse_transcript(data)}


class Transcript(BaseModel):
    """A transcript with provenance for the UI badge (NFR-022)."""

    text: str
    audio_sha256: str
    source: TranscriptSource
    cached: bool
    call_id: str | None = None
    model: str = VOICE
    duration_s: float | None = None
    fallback_reason: str | None = None


# ---------------------------------------------------------------------------
# Live path
# ---------------------------------------------------------------------------


def transcribe_wav(c, wav: bytes | Path, visit_id: str | None = None) -> Transcript:
    """Validate, then transcribe through MetaClient (cache by audio hash, budget, ledger).

    The audio stays in memory; only the transcript is cached.
    """
    data = _audio_bytes(wav)
    s = c.settings
    info = validate_wav(data, s.max_audio_s, s.max_audio_bytes)
    sha = audio_sha256(data)
    request_json, files = build_transcribe_request(data)
    resp = c.post_multipart(
        TRANSCRIBE_PATH,
        VOICE,
        PURPOSE,
        request_json=request_json,
        files=files,
        content_hash=sha,
        units={"audio_s": info.duration_s},
        visit_id=visit_id,
        feature="voice",
        cache_key=transcript_cache_key(sha),
        cache_filter=_transcript_only,
    )
    meta = resp.get("_vigil") or {}
    cached = bool(meta.get("cached"))
    return Transcript(
        text=parse_transcript(resp),
        audio_sha256=sha,
        source="cache" if cached else "live",
        cached=cached,
        call_id=meta.get("call_id"),
        duration_s=info.duration_s,
    )


def transcribe(c, audio: bytes | Path, visit_id: str | None = None) -> str:
    """Transcribe a short WAV recording (bytes, or a fixture path); return the text."""
    return transcribe_wav(c, audio, visit_id).text


# ---------------------------------------------------------------------------
# Fixture buttons (3 consented WAVs, spec 9.1 demo/voice/)
# ---------------------------------------------------------------------------


class AudioFixture(BaseModel):
    """One entry of ``config/audio_fixtures.json``."""

    id: str
    file: str
    """Path of the WAV relative to ``demo/voice/``."""
    sha256: str
    transcript: str | None = None
    """Cached transcript served offline, in cached mode and with an invalid key."""
    label: str | None = None


def load_fixtures(path: Path | str = FIXTURES_PATH) -> dict[str, AudioFixture]:
    """Read the fixture list: ``{"fixtures": [...]}``, a list, or a mapping of id to entry."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("fixtures"), list):
        raw = raw["fixtures"]
    if isinstance(raw, list):
        items = [AudioFixture.model_validate(e) for e in raw]
    elif isinstance(raw, dict):
        items = [AudioFixture.model_validate({"id": k, **v}) for k, v in raw.items()]
    else:
        raise ValueError(f"{path}: expected a list or mapping of audio fixtures")
    return {f.id: f for f in items}


def _fixture_audio(fx: AudioFixture, root: Path) -> bytes:
    base = root.resolve()
    path = (base / fx.file).resolve()
    if base not in path.parents:
        raise AudioRejected(f"fixture {fx.id} points outside {base.name}/")
    data = path.read_bytes()
    if audio_sha256(data) != fx.sha256:
        raise AudioRejected(
            f"fixture {fx.id} audio does not match its SHA-256 in config/audio_fixtures.json"
        )
    return data


def _cached_fixture(fx: AudioFixture, c, reason: str | None) -> Transcript:
    cache = getattr(c, "cache", None) if c is not None else None
    if cache is not None:
        hit = cache.get(transcript_cache_key(fx.sha256))
        if hit is not None:
            try:
                text = parse_transcript(hit)
            except TranscriptUnrecognised:
                text = None
            if text is not None:
                return Transcript(
                    text=text,
                    audio_sha256=fx.sha256,
                    source="cache",
                    cached=True,
                    fallback_reason=reason,
                )
    if fx.transcript is None:
        raise TranscriptUnavailable(f"fixture {fx.id} has no cached transcript")
    return Transcript(
        text=fx.transcript,
        audio_sha256=fx.sha256,
        source="fixture",
        cached=True,
        fallback_reason=reason,
    )


def transcribe_fixture(
    fixture_id: str,
    fixtures: dict[str, AudioFixture],
    c=None,
    *,
    live: bool = False,
    root: Path | None = None,
) -> Transcript:
    """Transcript for a fixture button.

    Offline (no client, or ``live=False``): the cached transcript, from the response cache
    entry for the fixture's hash when there is one, else the one in the fixture list. Live:
    the fixture's bytes are checked against its SHA-256 and sent; any refusal or failure
    (budget cap, invalid key, outage, bad audio) falls back to the cached transcript with
    the reason, so the button always works (FR-022, NFR-009).
    """
    fx = fixtures[fixture_id]
    reason: str | None = None
    if live and c is not None:
        try:
            return transcribe_wav(c, _fixture_audio(fx, root or FIXTURE_ROOT))
        except (MetaError, BudgetExceeded, AudioRejected, TranscriptUnrecognised, OSError) as exc:
            reason = str(exc)
    return _cached_fixture(fx, c, reason)
