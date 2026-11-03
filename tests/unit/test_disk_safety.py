"""FR-031/NFR-029: pinned evidence survives retention and a disk floor."""

from vigil.reolink.capture import cleanup_ring, segment_name


def test_event_pins_survive_retention_and_floor(tmp_path):
    from vigil.reolink.retention import PinIndex

    root = tmp_path / "ring"
    root.mkdir()
    paths = []
    for at in (100, 110, 120):
        p = root / segment_name("porch", at)
        p.write_bytes(b"x" * 20)
        paths.append(p)
    pins = PinIndex(root)
    pins.pin("event-1", [paths[0]])
    deleted = cleanup_ring(
        root,
        retention_s=10000,
        now=150,
        free_floor_bytes=40,
        free_bytes=lambda: 20 * sum(not p.exists() for p in paths),
    )
    assert deleted == paths[1:]
    assert paths[0].exists()
    assert PinIndex(root).pinned(paths[0])
    assert cleanup_ring(root, retention_s=1, now=150) == []
    pins.release("event-1")
    assert cleanup_ring(root, retention_s=1, now=150) == [paths[0]]


def test_retention_never_follows_links_outside_ring(tmp_path):
    import pytest

    from vigil.reolink.retention import PinIndex

    root = tmp_path / "ring"
    root.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"keep")
    with pytest.raises(ValueError, match="outside"):
        PinIndex(root).pin("event", [outside])
    assert outside.read_bytes() == b"keep"


def test_processing_retention_preserves_pinned_and_sqlite(tmp_path):
    import os

    from vigil.reolink.retention import cleanup_processing

    old = tmp_path / "old.mp4"
    pinned = tmp_path / "active.json"
    ledger = tmp_path / "ledger.sqlite"
    for p in (old, pinned, ledger):
        p.write_bytes(b"keep")
        os.utime(p, (1, 1))
    assert cleanup_processing(tmp_path, retention_s=10, now=100, pinned=[pinned]) == [old]
    assert pinned.exists()
    assert ledger.exists()
