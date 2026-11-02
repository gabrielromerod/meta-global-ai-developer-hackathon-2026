"""Request-hash response cache: identical requests are never paid twice (spec 11.6 item 4).

The key is the SHA-256 of the canonical JSON (sorted keys, no whitespace) of the model and
the full request body, so key order never matters. Entries are plain JSON files under
``<root>/<hh>/<hash>.json``; writes are atomic, and an unreadable entry is a miss.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, UTF-8, no NaN."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def request_hash(model: str, body: dict) -> str:
    """Stable hash of one request: same model and body (any key order) -> same hash."""
    payload = canonical_json({"model": model, "body": body})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_hash(path: Path, chunk: int = 1 << 20) -> str:
    """SHA-256 of a file's bytes (used to cache uploads and audio requests by content)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


class ResponseCache:
    """File-backed cache of raw model responses keyed by request hash."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path_for(self, key: str) -> Path:
        safe = "".join(ch for ch in key if ch.isalnum() or ch in "-_")
        if not safe:
            raise ValueError("empty cache key")
        return self.root / safe[:2] / f"{safe}.json"

    def get(self, key: str) -> dict | None:
        path = self.path_for(key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("unreadable cache entry %s treated as a miss: %s", path.name, exc)
            return None
        value = entry.get("response") if isinstance(entry, dict) else None
        return value if isinstance(value, dict) else None

    def put(self, key: str, response: dict, *, model: str | None = None) -> Path:
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            {"key": key, "model": model, "response": response},
            ensure_ascii=False,
            sort_keys=True,
            indent=1,
        )
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return path

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None
