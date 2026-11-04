"""Local SQLite store of face templates grouped into recurring-visitor profiles.

Opt-in only. Templates and crops stay in one SQLite file on this machine: they are never
sent to any model API, never exported, and never become an identity. A profile is
`fp_<8 hex>` until the owner names it; the name is the owner's label, nothing inferred.

A track joins the profile whose centroid (mean of its stored templates) is closest by
cosine, if at or above `SAME_FACE_COSINE`; otherwise it starts a new profile. Re-adding a
capture+track is a no-op. Retention: `purge_older_than` deletes faces and sightings past
the window, then profiles left empty. Erase: `delete_profile` hard-deletes a profile with
all its faces and sightings, at the owner's request.
"""

from __future__ import annotations

import secrets
import sqlite3
import unicodedata
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from vigil.faces.engine import SAME_FACE_COSINE, TrackFace, cosine, face_quality, normalise

NAME_MAX = 40
CROPS_PER_PROFILE = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
  id TEXT PRIMARY KEY, name TEXT NULL, created_at TEXT NOT NULL, flagged INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS faces (
  id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, capture_id TEXT NOT NULL,
  track_id TEXT NOT NULL, t REAL, seen_at TEXT NOT NULL, embedding BLOB NOT NULL,
  crop BLOB, quality REAL);
CREATE INDEX IF NOT EXISTS faces_profile ON faces(profile_id);
CREATE INDEX IF NOT EXISTS faces_track ON faces(capture_id, track_id);
CREATE TABLE IF NOT EXISTS sightings (
  profile_id TEXT NOT NULL, capture_id TEXT NOT NULL, seen_at TEXT NOT NULL,
  PRIMARY KEY (profile_id, capture_id));
"""


def _iso(when: datetime | str) -> str:
    """UTC ISO-8601, so stored times compare as strings; naive times are taken as UTC."""
    dt = datetime.fromisoformat(when) if isinstance(when, str) else when
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.isoformat()


def clean_name(name: str | None) -> str | None:
    """Owner label: stripped, at most 40 characters, no control characters; '' clears."""
    if name is None or not name.strip():
        return None
    name = name.strip()
    if len(name) > NAME_MAX:
        raise ValueError(f"name longer than {NAME_MAX} characters")
    if any(unicodedata.category(c).startswith("C") for c in name):
        raise ValueError("name contains control characters")
    return name


class FaceStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _centroids(self, db: sqlite3.Connection) -> dict[str, np.ndarray]:
        sums: dict[str, np.ndarray] = {}
        for r in db.execute("SELECT profile_id, embedding FROM faces"):
            v = np.frombuffer(r["embedding"], dtype=np.float32)
            sums[r["profile_id"]] = sums.get(r["profile_id"], 0) + v
        return {pid: normalise(v) for pid, v in sums.items()}

    def add_track_faces(
        self, capture_id: str, track_id: str, seen_at: datetime | str, faces: Iterable[TrackFace]
    ) -> str | None:
        """Attach one track's faces to a profile (matched or new); return its id."""
        faces = list(faces)
        if not faces:
            return None
        seen = _iso(seen_at)
        with self._db() as db:
            done = db.execute(
                "SELECT profile_id FROM faces WHERE capture_id=? AND track_id=? LIMIT 1",
                (capture_id, track_id),
            ).fetchone()
            if done:
                return done["profile_id"]
            mean = normalise(np.mean([normalise(f.embedding) for f in faces], axis=0))
            scored = [(cosine(mean, c), pid) for pid, c in self._centroids(db).items()]
            best = max(scored, default=(-1.0, None))
            pid = best[1] if best[0] >= SAME_FACE_COSINE else None
            if pid is None:
                pid = f"fp_{secrets.token_hex(4)}"
                db.execute(
                    "INSERT INTO profiles (id, created_at) VALUES (?, ?)",
                    (pid, _iso(datetime.now(UTC))),
                )
            db.executemany(
                "INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        f"fc_{secrets.token_hex(8)}",
                        pid,
                        capture_id,
                        track_id,
                        float(f.t),
                        seen,
                        normalise(f.embedding).tobytes(),
                        f.crop,
                        face_quality(f.face),
                    )
                    for f in faces
                ],
            )
            db.execute("INSERT OR IGNORE INTO sightings VALUES (?, ?, ?)", (pid, capture_id, seen))
        return pid

    def _profile(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict:
        sightings = [
            {"capture_id": s["capture_id"], "seen_at": s["seen_at"]}
            for s in db.execute(
                "SELECT capture_id, seen_at FROM sightings WHERE profile_id=? "
                "ORDER BY seen_at DESC, capture_id DESC",
                (row["id"],),
            )
        ]
        crops = [
            r["id"]
            for r in db.execute(
                "SELECT id FROM faces WHERE profile_id=? ORDER BY quality DESC, seen_at DESC "
                "LIMIT ?",
                (row["id"], CROPS_PER_PROFILE),
            )
        ]
        return {
            "id": row["id"],
            "name": row["name"],
            "flagged": bool(row["flagged"]),
            "sightings": sightings,
            "count": len(sightings),
            "crops": crops,
        }

    _SELECT = (
        "SELECT p.*, MAX(s.seen_at) AS last_seen, COUNT(s.capture_id) AS n "
        "FROM profiles p LEFT JOIN sightings s ON s.profile_id = p.id "
        "WHERE ?1 IS NULL OR p.id IN (SELECT profile_id FROM sightings WHERE capture_id = ?1) "
        "GROUP BY p.id HAVING n >= ?2 ORDER BY last_seen DESC, p.id"
    )

    def _select(self, capture_id: str | None, min_sightings: int) -> list[dict]:
        with self._db() as db:
            rows = db.execute(self._SELECT, (capture_id, min_sightings)).fetchall()
            return [self._profile(db, r) for r in rows]

    def profiles(self, min_sightings: int = 1) -> list[dict]:
        """All profiles with at least `min_sightings` captures, most recently seen first."""
        return self._select(None, min_sightings)

    def profile_for_capture(self, capture_id: str) -> list[dict]:
        """Profiles sighted in one capture (same dict shape as `profiles`)."""
        return self._select(capture_id, 1)

    def crop(self, face_id: str) -> bytes | None:
        with self._db() as db:
            row = db.execute("SELECT crop FROM faces WHERE id=?", (face_id,)).fetchone()
        return bytes(row["crop"]) if row and row["crop"] is not None else None

    def _update(self, profile_id: str, sql: str, args: tuple) -> None:
        with self._db() as db:
            if db.execute(sql, (*args, profile_id)).rowcount == 0:
                raise KeyError(profile_id)

    def rename(self, profile_id: str, name: str | None) -> None:
        self._update(profile_id, "UPDATE profiles SET name=? WHERE id=?", (clean_name(name),))

    def flag(self, profile_id: str, flagged: bool) -> None:
        self._update(profile_id, "UPDATE profiles SET flagged=? WHERE id=?", (int(flagged),))

    def merge(self, keep_id: str, drop_id: str) -> None:
        """Fold `drop_id` into `keep_id`: faces and sightings move; a flag carries over."""
        if keep_id == drop_id:
            raise ValueError("cannot merge a profile into itself")
        with self._db() as db:
            rows = {
                r["id"]: r
                for r in db.execute("SELECT * FROM profiles WHERE id IN (?, ?)", (keep_id, drop_id))
            }
            if set(rows) != {keep_id, drop_id}:
                raise KeyError(next(i for i in (keep_id, drop_id) if i not in rows))
            keep, drop = rows[keep_id], rows[drop_id]
            db.execute(
                "UPDATE profiles SET name=?, flagged=? WHERE id=?",
                (keep["name"] or drop["name"], keep["flagged"] or drop["flagged"], keep_id),
            )
            db.execute("UPDATE faces SET profile_id=? WHERE profile_id=?", (keep_id, drop_id))
            db.execute(
                "INSERT OR IGNORE INTO sightings SELECT ?, capture_id, seen_at "
                "FROM sightings WHERE profile_id=?",
                (keep_id, drop_id),
            )
            db.execute("DELETE FROM sightings WHERE profile_id=?", (drop_id,))
            db.execute("DELETE FROM profiles WHERE id=?", (drop_id,))

    def delete_profile(self, profile_id: str) -> None:
        """Owner's erase: hard-delete the profile, its faces and its sightings."""
        with self._db() as db:
            db.execute("DELETE FROM faces WHERE profile_id=?", (profile_id,))
            db.execute("DELETE FROM sightings WHERE profile_id=?", (profile_id,))
            db.execute("DELETE FROM profiles WHERE id=?", (profile_id,))

    def purge_older_than(self, days: int, now: datetime | str | None = None) -> dict[str, int]:
        """Retention: drop faces and sightings older than `days`, then empty profiles."""
        cutoff = _iso(datetime.fromisoformat(_iso(now or datetime.now(UTC))) - timedelta(days))
        with self._db() as db:
            faces = db.execute("DELETE FROM faces WHERE seen_at < ?", (cutoff,)).rowcount
            seen = db.execute("DELETE FROM sightings WHERE seen_at < ?", (cutoff,)).rowcount
            profiles = db.execute(
                "DELETE FROM profiles WHERE id NOT IN (SELECT profile_id FROM faces) "
                "AND id NOT IN (SELECT profile_id FROM sightings)"
            ).rowcount
        return {"faces": faces, "sightings": seen, "profiles": profiles}
