"""Muse Voice Transcribe for voice rules (FR-022, P2).

Endpoint per https://dev.meta.ai/docs/api-reference/voice/transcribe (read 2026-11-02):
``POST /v1/asr/transcribe``, ``multipart/form-data`` with a ``request`` JSON part
(``model``, ``audioEncoding: "WAV"``, ``mode: "PUSH_TO_TALK"``) and an ``audio`` part.
The API accepts WAV up to 10 minutes and 32 MB; Vigil's own limits are stricter
(30 s and 2 MB, NFR-015) and are enforced here before anything is sent.

The ``TranscribeResponse`` body fields are not documented in detail, so the parser accepts
``transcript`` / ``text`` or a list of turns; an unrecognised body raises
:class:`TranscriptUnrecognised` (verify with the T-03 smoke test).
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

from vigil.meta.budget import VOICE
from vigil.meta.cache import file_hash

TRANSCRIBE_PATH = "/asr/transcribe"
REQUEST = {"model": VOICE, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}


class AudioRejected(ValueError):
    """Audio refused before sending (maps to HTTP 413/400 at the API layer)."""


class AudioTooLong(AudioRejected):
    pass


class AudioTooLarge(AudioRejected):
    pass


class TranscriptUnrecognised(RuntimeError):
    """The transcribe response had no transcript Vigil could read."""


def wav_duration_s(audio: Path) -> float:
    try:
        with wave.open(str(audio), "rb") as w:
            rate = w.getframerate()
            return w.getnframes() / float(rate) if rate else 0.0
    except (wave.Error, EOFError) as exc:
        raise AudioRejected(f"audio must be a PCM WAV file: {exc}") from None


def check_audio(audio: Path, max_s: float, max_bytes: int) -> float:
    """Enforce the 30 s / 2 MB limits (NFR-015); return the duration in seconds."""
    size = Path(audio).stat().st_size
    if size > max_bytes:
        raise AudioTooLarge(f"audio is {size} bytes; the limit is {max_bytes} bytes")
    duration = wav_duration_s(audio)
    if duration > max_s:
        raise AudioTooLong(f"audio is {duration:.1f} s; the limit is {max_s:.0f} s")
    return duration


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
    raise TranscriptUnrecognised(f"no transcript in response keys {sorted(data)[:10]}")


def transcribe(c, audio: Path, visit_id: str | None = None) -> str:
    """Transcribe a short WAV recording through MetaClient (cache, budget, ledger)."""
    audio = Path(audio)
    s = c.settings
    duration = check_audio(audio, s.max_audio_s, s.max_audio_bytes)
    resp = c.post_multipart(
        TRANSCRIBE_PATH,
        VOICE,
        "voice_rule_transcribe",
        request_json=dict(REQUEST),
        files={"audio": (audio.name, audio.read_bytes(), "audio/wav")},
        content_hash=file_hash(audio),
        units={"audio_s": duration},
        visit_id=visit_id,
        feature="voice",
    )
    return parse_transcript(resp)
