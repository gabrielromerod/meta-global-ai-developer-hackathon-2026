"""CLI shim for the shared fail-closed metadata scanner."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vigil.ingest.metadata import main, scan

__all__ = ["scan"]

if __name__ == "__main__":
    raise SystemExit(main())
