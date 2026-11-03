"""Durable event pins and bounded retention. SQLite serializes pin/delete races."""

import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path


class PinIndex:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS pins(event_id TEXT, path TEXT, "
                "PRIMARY KEY(event_id,path))"
            )

    def relative(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("retention path is outside its root")
        return resolved.relative_to(self.root).as_posix()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.root / ".event-pins.sqlite", timeout=30)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def pin(self, event_id: str, paths: Sequence[Path]) -> None:
        relative = [self.relative(p) for p in paths]
        with self.transaction() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO pins VALUES (?,?)", [(event_id, p) for p in relative]
            )

    def release(self, event_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM pins WHERE event_id=?", (event_id,))

    def pinned(self, path: Path) -> bool:
        relative = self.relative(path)
        with self.transaction() as conn:
            return (
                conn.execute("SELECT 1 FROM pins WHERE path=? LIMIT 1", (relative,)).fetchone()
                is not None
            )


def cleanup_processing(
    root: Path,
    retention_s: float,
    *,
    now: float | None = None,
    pinned: Sequence[Path] = (),
) -> list[Path]:
    root = root.resolve()
    if not root.exists():
        return []
    protected = {p.resolve() for p in pinned}
    cutoff = (time.time() if now is None else now) - retention_s
    allowed = {".mp4", ".json", ".jpg", ".png", ".webp", ".txt", ".npz"}
    deleted = []
    index = PinIndex(root)
    with index.transaction() as conn:
        for path in sorted(root.rglob("*"), key=lambda p: p.name):
            resolved = path.resolve()
            if not resolved.is_relative_to(root) or path.is_symlink() or not path.is_file():
                continue
            if (
                path.suffix.lower() not in allowed
                or resolved in protected
                or path.stat().st_mtime >= cutoff
            ):
                continue
            if conn.execute(
                "SELECT 1 FROM pins WHERE path=? LIMIT 1", (index.relative(path),)
            ).fetchone():
                continue
            path.unlink()
            deleted.append(path)
    return deleted
