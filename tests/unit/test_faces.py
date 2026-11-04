"""Local face templates for recurring visitors: engine helpers and the SQLite store.

Embeddings are synthetic unit vectors (two "people" = two random directions plus small
noise); detector and embedder are fakes. No model files, images or network are used.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from vigil.faces import (
    MAX_FACES_PER_TRACK,
    MIN_FACE_PX,
    SAME_FACE_COSINE,
    FaceBox,
    FaceEngine,
    FaceStore,
    FacesUnavailable,
    TrackFace,
    best_faces_for_track,
    cosine,
    crop_face,
)

DIM = 128
T0 = datetime(2026, 11, 1, 18, 0, tzinfo=UTC)


@pytest.fixture
def people():
    rng = np.random.default_rng(7)
    dirs = [rng.normal(size=DIM) for _ in range(2)]

    def sample(who: int) -> np.ndarray:
        v = dirs[who] / np.linalg.norm(dirs[who]) + rng.normal(scale=0.03, size=DIM)
        return (v / np.linalg.norm(v)).astype(np.float32)

    return sample


def _face(x: float = 10, y: float = 10, w: float = 40, score: float = 0.9) -> FaceBox:
    lm = tuple((x + w * fx, y + w * fy) for fx, fy in ((0.3, 0.4), (0.7, 0.4), (0.5, 0.6)))
    lm += ((x + w * 0.35, y + w * 0.8), (x + w * 0.65, y + w * 0.8))
    return FaceBox(box=(x, y, w, w), landmarks=lm, score=score)


def _faces(sample, who: int, n: int = 2) -> list[TrackFace]:
    return [TrackFace(i * 0.5, _face(score=0.8 + i * 0.05), sample(who), b"jpg") for i in range(n)]


@pytest.fixture
def store(tmp_path):
    return FaceStore(tmp_path / "faces.sqlite")


def _count(store: FaceStore, table: str) -> int:
    with sqlite3.connect(store.path) as db:
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_cosine_and_threshold():
    a = np.array([1.0, 0.0], dtype=np.float32)
    assert cosine(a, a) == pytest.approx(1.0)
    assert cosine(a, np.array([0.0, 2.0])) == pytest.approx(0.0)
    assert cosine(a, np.zeros(2)) == 0.0
    assert SAME_FACE_COSINE == 0.363


def test_same_person_across_captures_is_one_profile(store, people):
    for i in range(4):
        pid = store.add_track_faces(f"cap{i}", "trk1", T0 + timedelta(days=i), _faces(people, 0))
        assert pid is not None
    profiles = store.profiles()
    assert len(profiles) == 1
    p = profiles[0]
    assert p["id"].startswith("fp_")
    assert len(p["id"]) == 11
    assert p["count"] == 4
    assert p["name"] is None
    assert p["flagged"] is False
    assert [s["capture_id"] for s in p["sightings"]] == ["cap3", "cap2", "cap1", "cap0"]
    assert len(p["crops"]) == 4
    assert store.crop(p["crops"][0]) == b"jpg"
    assert store.crop("nope") is None
    assert [q["id"] for q in store.profile_for_capture("cap2")] == [p["id"]]
    assert store.profile_for_capture("other") == []


def test_two_people_two_profiles(store, people):
    a = store.add_track_faces("cap0", "t1", T0, _faces(people, 0))
    b = store.add_track_faces("cap1", "t1", T0 + timedelta(hours=1), _faces(people, 1))
    assert a != b
    assert [p["id"] for p in store.profiles()] == [b, a]  # most recent sighting first
    assert {p["id"] for p in store.profile_for_capture("cap0")} == {a}


def test_min_sightings_filter(store, people):
    a = store.add_track_faces("cap0", "t1", T0, _faces(people, 0))
    store.add_track_faces("cap1", "t1", T0, _faces(people, 0))
    store.add_track_faces("cap2", "t1", T0, _faces(people, 1))
    assert [p["id"] for p in store.profiles(min_sightings=2)] == [a]


def test_readd_same_track_is_idempotent(store, people):
    faces = _faces(people, 0, n=3)
    first = store.add_track_faces("cap0", "t1", T0, faces)
    again = store.add_track_faces("cap0", "t1", T0, faces)
    assert first == again
    assert _count(store, "faces") == 3
    assert _count(store, "sightings") == 1
    # a second track of the same person in the same capture adds faces, not a sighting
    store.add_track_faces("cap0", "t2", T0, _faces(people, 0))
    assert _count(store, "faces") == 5
    assert _count(store, "sightings") == 1


def test_empty_faces_returns_none(store):
    assert store.add_track_faces("cap0", "t1", T0, []) is None
    assert store.profiles() == []


def test_rename_validation(store, people):
    pid = store.add_track_faces("cap0", "t1", T0, _faces(people, 0))
    store.rename(pid, "  Courier  ")
    assert store.profiles()[0]["name"] == "Courier"
    with pytest.raises(ValueError, match="40"):
        store.rename(pid, "x" * 41)
    with pytest.raises(ValueError, match="control"):
        store.rename(pid, "bad\nname")
    store.rename(pid, None)
    assert store.profiles()[0]["name"] is None
    with pytest.raises(KeyError):
        store.rename("fp_missing", "x")


def test_flag(store, people):
    pid = store.add_track_faces("cap0", "t1", T0, _faces(people, 0))
    store.flag(pid, True)
    assert store.profiles()[0]["flagged"] is True
    store.flag(pid, False)
    assert store.profiles()[0]["flagged"] is False


def test_merge(store, people):
    a = store.add_track_faces("cap0", "t1", T0, _faces(people, 0))
    b = store.add_track_faces("cap1", "t1", T0 + timedelta(hours=1), _faces(people, 1))
    store.flag(b, True)
    store.merge(a, b)
    (p,) = store.profiles()
    assert p["id"] == a
    assert p["count"] == 2
    assert p["flagged"] is True
    assert _count(store, "faces") == 4
    with pytest.raises(ValueError):
        store.merge(a, a)


def test_delete_profile_removes_rows(store, people):
    a = store.add_track_faces("cap0", "t1", T0, _faces(people, 0))
    b = store.add_track_faces("cap0", "t2", T0, _faces(people, 1))
    store.delete_profile(a)
    assert [p["id"] for p in store.profiles()] == [b]
    assert _count(store, "faces") == 2
    assert _count(store, "sightings") == 1
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM faces WHERE profile_id=?", (a,)).fetchone()[0] == 0


def test_purge_by_age(store, people):
    old = store.add_track_faces("cap0", "t1", T0 - timedelta(days=40), _faces(people, 1))
    keep = store.add_track_faces("cap1", "t1", T0 - timedelta(days=40), _faces(people, 0))
    store.add_track_faces("cap2", "t1", T0 - timedelta(days=1), _faces(people, 0))
    removed = store.purge_older_than(30, now=T0)
    assert removed == {"faces": 4, "sightings": 2, "profiles": 1}
    (p,) = store.profiles()
    assert p["id"] == keep != old
    assert [s["capture_id"] for s in p["sightings"]] == ["cap2"]


def _frame(h: int = 200, w: int = 120) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_best_faces_for_track_filters_and_caps():
    person = (0, 0, 120, 200)  # head region = top 45% = y < 90
    calls: list[tuple] = []

    def detect(frame, *, roi):
        calls.append(roi)
        return [
            _face(x=10, y=10, w=MIN_FACE_PX - 1, score=0.99),  # too small
            _face(x=10, y=120, w=40, score=0.99),  # on the torso, outside head region
            _face(x=30, y=20, w=40, score=0.8 + len(calls) * 0.01),
        ]

    def embed(frame, face):
        return np.ones(4, dtype=np.float32) / 2

    samples = [(i * 0.1, _frame(), person) for i in range(8)]
    out = best_faces_for_track(samples, detect=detect, embed=embed, crop=lambda f, b: b"c")
    assert calls[0] == (0, 0, 120, 90)
    assert len(out) == MAX_FACES_PER_TRACK == 5
    assert all(tf.face.box[2] >= MIN_FACE_PX and tf.face.box[1] == 20 for tf in out)
    # best score first: the last samples had the highest detection scores
    assert [tf.t for tf in out] == pytest.approx([0.7, 0.6, 0.5, 0.4, 0.3])
    assert out[0].crop == b"c"
    assert out[0].embedding.shape == (4,)


def test_best_faces_for_track_none_found():
    out = best_faces_for_track(
        [(0.0, _frame(), (0, 0, 120, 200))],
        detect=lambda frame, *, roi: [],
        embed=lambda f, b: np.zeros(4),
    )
    assert out == []


def test_crop_face_is_small_jpeg():
    frame = np.full((600, 600, 3), 128, dtype=np.uint8)
    data = crop_face(frame, _face(x=100, y=100, w=300))
    assert data[:2] == b"\xff\xd8"
    import cv2

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert max(img.shape[:2]) <= 160


def test_missing_model_raises_faces_unavailable(tmp_path):
    engine = FaceEngine(tmp_path)  # construction is lazy and never raises
    with pytest.raises(FacesUnavailable, match=r"face_detection_yunet_2023mar\.onnx") as exc:
        engine.detect(_frame())
    assert "face_recognition_sface_2021dec.onnx" in str(exc.value)
    (tmp_path / "face_detection_yunet_2023mar.onnx").write_bytes(b"")
    with pytest.raises(FacesUnavailable) as exc:
        engine.embed(_frame(), _face())
    assert "face_recognition_sface_2021dec.onnx" in str(exc.value)
    assert "yunet" not in str(exc.value)
