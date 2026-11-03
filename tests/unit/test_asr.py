"""Muse Voice Transcribe for voice rules (FR-022, NFR-002, NFR-015, spec 12.1 test_asr).

Offline: respx intercepts every request. WAV files are generated in memory at test time.
"""

from __future__ import annotations

import hashlib
import io
import json
import random
import struct
import wave
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from vigil.meta.asr import (
    ENDPOINT_CONFIRMED,
    MAX_AUDIO_BYTES,
    MAX_AUDIO_S,
    REQUEST,
    TRANSCRIBE_PATH,
    AudioFixture,
    AudioFormatRejected,
    AudioRejected,
    AudioTooLarge,
    AudioTooLong,
    Transcript,
    TranscriptUnavailable,
    TranscriptUnrecognised,
    build_transcribe_request,
    load_fixtures,
    parse_transcript,
    transcribe,
    transcribe_fixture,
    transcribe_wav,
    transcript_cache_key,
    validate_wav,
)
from vigil.meta.budget import BudgetGuard
from vigil.meta.cache import ResponseCache
from vigil.meta.client import CallLedger, MetaClient
from vigil.settings import Settings

BASE = "https://api.meta.ai/v1"
KEY = "sk-test-asr-000"
NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)
TEXT = "tell me if anyone except family opens the side gate after dark"


def wav_bytes(
    seconds: float,
    *,
    rate: int = 16_000,
    channels: int = 1,
    width: int = 2,
    seed: int = 0,
) -> bytes:
    """A WAV generated in memory (never on disk); ``seed`` varies the samples."""
    rng = random.Random(seed)
    frames = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        if width == 2:
            sample = b"".join(struct.pack("<h", rng.randint(-200, 200)) for _ in range(64))
        else:
            sample = bytes(rng.randint(0, 255) for _ in range(64 * width))
        block = sample * channels
        n_blocks, rest = divmod(frames, 64)
        w.writeframes(block * n_blocks + block[: rest * width * channels])
    return buf.getvalue()


class Env:
    def __init__(self, tmp_path: Path, **kw):
        kw.setdefault("MODEL_API_KEY", KEY)
        self.settings = Settings(_env_file=None, cache_dir=tmp_path / "cache", **kw)
        self.cache_root = tmp_path / "cache" / "meta"
        self.ledger = CallLedger()
        self.cache = ResponseCache(self.cache_root)
        self.guard = BudgetGuard(self.settings, clock=lambda: NOW)

    def client(self, **kw) -> MetaClient:
        return MetaClient(
            self.settings,
            ledger=self.ledger,
            cache=self.cache,
            budget=self.guard,
            clock=lambda: NOW,
            sleep=lambda s: None,
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


# --- WAV validation before sending (FR-022, NFR-015) ---------------------------------------


def test_limits_are_30_seconds_and_2_mb():
    assert MAX_AUDIO_S == 30
    assert MAX_AUDIO_BYTES == 2 * 1024 * 1024


def test_validate_wav_accepts_16k_mono_16bit_pcm():
    info = validate_wav(wav_bytes(4.0))
    assert info.sample_rate == 16_000
    assert info.channels == 1
    assert info.bits_per_sample == 2 * 8
    assert info.duration_s == pytest.approx(4.0)


def test_a_30_second_recording_is_under_2_mb():
    data = wav_bytes(30.0)
    assert len(data) < 2 * 1024 * 1024  # about 0.96 MB (FR-022 acceptance)
    assert validate_wav(data).duration_s == pytest.approx(30.0)


def test_validate_wav_rejects_over_30_seconds():
    with pytest.raises(AudioTooLong, match="30"):
        validate_wav(wav_bytes(30.5))


def test_validate_wav_rejects_over_2_mb_before_parsing():
    with pytest.raises(AudioTooLarge):
        validate_wav(b"RIFF" + b"\x00" * (2 * 1024 * 1024 + 1))


@pytest.mark.parametrize(
    ("kw", "word"),
    [
        ({"rate": 44_100}, "16000"),
        ({"rate": 8_000}, "16000"),
        ({"channels": 2}, "mono"),
        ({"width": 1}, "16-bit"),
        ({"width": 3}, "16-bit"),
    ],
)
def test_validate_wav_rejects_other_formats(kw, word):
    with pytest.raises(AudioFormatRejected, match=word):
        validate_wav(wav_bytes(1.0, **kw))


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a wav file at all",
        b"OggS" + b"\x00" * 64,
        b"RIFF\x24\x00\x00\x00WAVE",  # header only, no fmt or data chunk
    ],
)
def test_validate_wav_rejects_non_wav(data):
    with pytest.raises(AudioRejected):
        validate_wav(data)


def test_validate_wav_rejects_non_pcm_format_code():
    data = bytearray(wav_bytes(1.0))
    fmt = data.index(b"fmt ")
    data[fmt + 8 : fmt + 10] = struct.pack("<H", 3)  # IEEE float
    with pytest.raises(AudioFormatRejected, match="PCM"):
        validate_wav(bytes(data))


def test_validate_wav_trusts_bytes_present_not_a_lying_data_size():
    data = bytearray(wav_bytes(2.0))
    pos = data.index(b"data")
    data[pos + 4 : pos + 8] = struct.pack("<I", 0xFFFFFFFF)  # streaming-style size
    assert validate_wav(bytes(data)).duration_s == pytest.approx(2.0)


# --- request builder (batch endpoint, confirm at T-03) -------------------------------------


def test_request_builder_shape():
    data = wav_bytes(1.0)
    request_json, files = build_transcribe_request(data)
    assert request_json == REQUEST
    assert request_json["model"] == "muse-voice-transcribe-1.0"
    assert request_json["audioEncoding"] == "WAV"
    name, content, mime = files["audio"]
    assert content is data
    assert mime == "audio/wav"
    assert name == "rule.wav"  # never the uploader's file name
    assert TRANSCRIBE_PATH == "/asr/transcribe"
    assert ENDPOINT_CONFIRMED is False  # flipped only after the T-03 smoke test


@pytest.mark.parametrize(
    ("body", "text"),
    [
        ({"transcript": " hello "}, "hello"),
        ({"text": "hi"}, "hi"),
        ({"turns": [{"transcript": "a"}, {"text": "b"}]}, "a b"),
        ({"results": [{"transcript": "only"}]}, "only"),
    ],
)
def test_recorded_transcribe_responses_parse(body, text):
    assert parse_transcript(body) == text


def test_unrecognised_response_raises():
    with pytest.raises(TranscriptUnrecognised):
        parse_transcript({"status": "ok"})


# --- live path: cache by audio hash, audio never persisted (NFR-002) -----------------------


def _all_bytes(root: Path) -> list[bytes]:
    return [p.read_bytes() for p in root.rglob("*") if p.is_file()] if root.exists() else []


def test_transcribe_wav_sends_once_and_caches_transcript_by_audio_hash(env: Env, router):
    route = router.post(TRANSCRIBE_PATH).mock(
        return_value=httpx.Response(
            200, json={"transcript": TEXT, "words": [{"w": "tell", "t": 0.1}]}
        )
    )
    data = wav_bytes(4.0, seed=1)
    first = transcribe_wav(env.client(), data)
    assert isinstance(first, Transcript)
    assert first.text == TEXT
    assert first.cached is False
    assert first.audio_sha256 == hashlib.sha256(data).hexdigest()
    assert first.call_id
    assert first.call_id.startswith("mc_")
    assert first.duration_s == pytest.approx(4.0)

    # Same bytes again (any file name, any caller): the cache answers, no second request.
    second = transcribe_wav(env.client(), bytes(data))
    assert second.text == TEXT
    assert second.cached is True
    assert route.call_count == 1
    rows = env.ledger.rows()
    assert [r.cached for r in rows] == [False, True]
    assert rows[0].cost_usd == pytest.approx(4 / 3600 * 0.18)
    assert rows[1].cost_usd == 0.0

    # The cache entry is keyed by the audio hash and holds only the transcript.
    entry = env.cache.path_for(transcript_cache_key(first.audio_sha256))
    assert entry.exists()
    stored = json.loads(entry.read_text(encoding="utf-8"))["response"]
    assert stored == {"transcript": TEXT}


def test_audio_is_never_written_to_disk_or_the_response_cache(env: Env, router, tmp_path: Path):
    router.post(TRANSCRIBE_PATH).mock(return_value=httpx.Response(200, json={"text": TEXT}))
    data = wav_bytes(3.0, seed=2)
    before = {p for p in tmp_path.rglob("*")}
    transcribe_wav(env.client(), data)
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    new_files = after - before
    assert new_files, "the transcript should have been cached"
    assert all(p.suffix == ".json" for p in new_files)
    for blob in _all_bytes(tmp_path):
        assert b"RIFF" not in blob
        assert b"WAVE" not in blob
        assert data[44:108] not in blob  # no slice of the PCM samples either


def test_rejected_audio_is_never_sent(env: Env, router):
    route = router.post(TRANSCRIBE_PATH).mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AudioTooLong):
        transcribe_wav(env.client(), wav_bytes(31.0))
    with pytest.raises(AudioFormatRejected):
        transcribe_wav(env.client(), wav_bytes(2.0, rate=48_000))
    assert route.call_count == 0
    assert env.ledger.rows() == []


def test_transcribe_accepts_a_path_and_returns_text(env: Env, router, tmp_path: Path):
    router.post(TRANSCRIBE_PATH).mock(return_value=httpx.Response(200, json={"text": TEXT}))
    path = tmp_path / "fixture.wav"
    path.write_bytes(wav_bytes(2.0, seed=3))
    assert transcribe(env.client(), path) == TEXT
    assert transcribe(env.client(), path.read_bytes()) == TEXT


def test_unparseable_response_is_not_cached(env: Env, router):
    route = router.post(TRANSCRIBE_PATH).mock(return_value=httpx.Response(200, json={"x": 1}))
    data = wav_bytes(1.0, seed=4)
    with pytest.raises(TranscriptUnrecognised):
        transcribe_wav(env.client(), data)
    sha = hashlib.sha256(data).hexdigest()
    assert env.cache.get(transcript_cache_key(sha)) is None
    with pytest.raises(TranscriptUnrecognised):
        transcribe_wav(env.client(), data)
    assert route.call_count == 2


# --- fixture buttons (3 consented WAVs with cached transcripts) ----------------------------


def _fixtures(tmp_path: Path) -> dict[str, AudioFixture]:
    out = {}
    for i, text in enumerate(
        [
            "tell me if anyone except family touches the bin after 9 PM",
            "alert me if a stranger opens the side gate at night",
            "let me know if anyone enters the backyard",
        ],
        start=1,
    ):
        data = wav_bytes(2.0, seed=10 + i)
        path = tmp_path / f"rule_{i}.wav"
        path.write_bytes(data)
        out[f"voice_{i}"] = AudioFixture(
            id=f"voice_{i}",
            file=path.name,
            sha256=hashlib.sha256(data).hexdigest(),
            transcript=text,
        )
    return out


def test_load_fixtures_accepts_list_or_mapping(tmp_path: Path):
    fx = _fixtures(tmp_path)
    as_list = [f.model_dump() for f in fx.values()]
    path = tmp_path / "audio_fixtures.json"
    path.write_text(json.dumps({"fixtures": as_list}), encoding="utf-8")
    assert load_fixtures(path) == fx
    path.write_text(json.dumps({k: v.model_dump() for k, v in fx.items()}), encoding="utf-8")
    assert load_fixtures(path) == fx


def test_fixture_offline_returns_cached_transcript_without_a_call(tmp_path: Path, router):
    route = router.post(TRANSCRIBE_PATH).mock(return_value=httpx.Response(200, json={}))
    fx = _fixtures(tmp_path)
    out = transcribe_fixture("voice_2", fx)
    assert out.text == "alert me if a stranger opens the side gate at night"
    assert out.cached is True
    assert out.source == "fixture"
    assert out.audio_sha256 == fx["voice_2"].sha256
    assert route.call_count == 0


def test_fixture_prefers_the_response_cache_entry_for_its_hash(env: Env, tmp_path: Path):
    fx = _fixtures(tmp_path)
    env.cache.put(transcript_cache_key(fx["voice_1"].sha256), {"transcript": "recorded live"})
    c = env.client(cache_only=True)
    out = transcribe_fixture("voice_1", fx, c)
    assert out.text == "recorded live"
    assert out.source == "cache"


def test_fixture_live_then_cached(env: Env, router, tmp_path: Path):
    route = router.post(TRANSCRIBE_PATH).mock(
        return_value=httpx.Response(200, json={"transcript": "live words"})
    )
    fx = _fixtures(tmp_path)
    out = transcribe_fixture("voice_3", fx, env.client(), live=True, root=tmp_path)
    assert out.text == "live words"
    assert out.source == "live"
    again = transcribe_fixture("voice_3", fx, env.client(), live=True, root=tmp_path)
    assert again.cached is True
    assert route.call_count == 1


def test_fixture_live_with_invalid_key_falls_back_to_cached_transcript(tmp_path: Path, router):
    env = Env(tmp_path, MODEL_API_KEY="invalid")
    router.post(TRANSCRIBE_PATH).mock(
        return_value=httpx.Response(401, json={"error": {"message": "invalid key"}})
    )
    fx = _fixtures(tmp_path)
    out = transcribe_fixture("voice_1", fx, env.client(), live=True, root=tmp_path)
    assert out.text == fx["voice_1"].transcript
    assert out.source == "fixture"
    assert out.fallback_reason
    assert "401" in out.fallback_reason


def test_fixture_with_wrong_hash_is_refused_live(env: Env, router, tmp_path: Path):
    route = router.post(TRANSCRIBE_PATH).mock(return_value=httpx.Response(200, json={}))
    fx = _fixtures(tmp_path)
    (tmp_path / fx["voice_1"].file).write_bytes(wav_bytes(2.0, seed=99))
    out = transcribe_fixture("voice_1", fx, env.client(), live=True, root=tmp_path)
    assert out.source == "fixture"
    assert "SHA-256" in (out.fallback_reason or "")
    assert route.call_count == 0


def test_unknown_fixture_and_missing_transcript(tmp_path: Path):
    fx = _fixtures(tmp_path)
    with pytest.raises(KeyError):
        transcribe_fixture("voice_9", fx)
    bare = {"v": fx["voice_1"].model_copy(update={"transcript": None})}
    with pytest.raises(TranscriptUnavailable):
        transcribe_fixture("v", bare)
