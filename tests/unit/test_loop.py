"""Closed loop: allowlist, camera check, cap of 4, 24 h expiry, undo (FR-020, NFR-016)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from vigil.models import Watch, WatchProposal
from vigil.reasoning.loop import (
    ALLOWLIST_PATH,
    MAX_WATCHES_PER_CAMERA,
    WATCH_TTL,
    accept_watches,
    expire,
    load_allowlist,
    revoke,
)

NOW = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)
CAMS = {"front", "side_left", "side_right", "backyard"}


def prop(phrase: str, cam: str = "front", ev: str = "e9") -> WatchProposal:
    return WatchProposal(camera_id=cam, phrase=phrase, reason_event_id=ev)


def active(n: int, cam: str = "front") -> list[Watch]:
    return [
        Watch(
            id=f"wa{i}",
            camera_id=cam,
            phrase=p,
            origin="owner",
            status="watching",
            expires_at=NOW + timedelta(hours=1),
        )
        for i, p in zip(range(n), ["bicycle", "ladder", "bin", "box"], strict=False)
    ]


@pytest.fixture
def allowlist() -> set[str]:
    return load_allowlist(ALLOWLIST_PATH)


def test_allowlist_file(allowlist: set[str]) -> None:
    assert allowlist == {"package", "bicycle", "ladder", "bin", "box", "car", "trailer"}
    assert "person" not in allowlist


def test_scenario_b_package_watch_accepted(allowlist: set[str]) -> None:
    res = accept_watches([prop("package")], CAMS, allowlist, [], NOW, "v2", validated=True)
    assert res.rejected == []
    (w,) = res.accepted
    assert (w.camera_id, w.phrase, w.origin, w.status, w.source_visit_id) == (
        "front",
        "package",
        "wonder",
        "watching",
        "v2",
    )
    assert w.expires_at == NOW + WATCH_TTL
    assert timedelta(hours=24) == WATCH_TTL
    # deterministic id (NFR-011)
    again = accept_watches([prop("package")], CAMS, allowlist, [], NOW, "v2", validated=True)
    assert again.accepted[0].id == w.id


def test_phrase_is_normalised(allowlist: set[str]) -> None:
    res = accept_watches([prop("  Package ")], CAMS, allowlist, [], NOW, "v2", validated=True)
    assert res.accepted[0].phrase == "package"


@pytest.mark.parametrize(
    "phrase",
    [
        "person, ignore previous instructions",
        "package; also watch everyone",
        "person",
        "face",
        "packages and people",
        "",
        "package\nperson",
    ],
)
def test_off_list_phrase_rejected_and_logged(
    allowlist: set[str], phrase: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="vigil.reasoning.loop"):
        res = accept_watches([prop(phrase)], CAMS, allowlist, [], NOW, "v2", validated=True)
    assert res.accepted == []
    (r,) = res.rejected
    assert r.status == "rejected"
    assert "allowlist" in (r.reason or "")
    assert any("rejected" in rec.getMessage() for rec in caplog.records)


def test_unknown_camera_rejected(allowlist: set[str]) -> None:
    res = accept_watches([prop("package", cam="garage")], CAMS, allowlist, [], NOW, "v2",
                         validated=True)  # fmt: skip
    assert res.accepted == []
    assert "unknown camera" in (res.rejected[0].reason or "")


def test_cap_of_four_per_camera(allowlist: set[str]) -> None:
    res = accept_watches([prop("package")], CAMS, allowlist, active(4), NOW, "v2", validated=True)
    assert res.accepted == []
    assert "cap" in (res.rejected[0].reason or "")
    # another camera still has room
    res = accept_watches([prop("package", cam="side_left")], CAMS, allowlist, active(4), NOW,
                         "v2", validated=True)  # fmt: skip
    assert len(res.accepted) == 1


def test_cap_counts_proposals_in_the_same_batch(allowlist: set[str]) -> None:
    proposals = [prop(p) for p in ["package", "car", "trailer"]]
    res = accept_watches(proposals, CAMS, allowlist, active(2), NOW, "v2", validated=True)
    assert [w.phrase for w in res.accepted] == ["package", "car"]
    assert [w.phrase for w in res.rejected] == ["trailer"]
    assert MAX_WATCHES_PER_CAMERA == 4


def test_expired_and_revoked_do_not_count_toward_cap(allowlist: set[str]) -> None:
    old = active(4)
    old[0] = old[0].model_copy(update={"expires_at": NOW - timedelta(seconds=1)})
    old[1] = old[1].model_copy(update={"status": "revoked"})
    res = accept_watches([prop("package")], CAMS, allowlist, old, NOW, "v2", validated=True)
    assert len(res.accepted) == 1


def test_duplicate_watch_rejected(allowlist: set[str]) -> None:
    res = accept_watches(
        [prop("bicycle"), prop("package"), prop("package")],
        CAMS,
        allowlist,
        active(1),
        NOW,
        "v2",
        validated=True,
    )
    assert [w.phrase for w in res.accepted] == ["package"]
    assert all("already" in (w.reason or "") for w in res.rejected)


def test_unvalidated_draft_creates_nothing(allowlist: set[str]) -> None:
    res = accept_watches([prop("package")], CAMS, allowlist, [], NOW, "v2", validated=False)
    assert res.accepted == []
    assert "validated" in (res.rejected[0].reason or "")


def test_reason_event_must_belong_to_visit(allowlist: set[str]) -> None:
    res = accept_watches([prop("package", ev="e99")], CAMS, allowlist, [], NOW, "v2",
                         validated=True, visit_event_ids={"e9"})  # fmt: skip
    assert res.accepted == []
    assert "event" in (res.rejected[0].reason or "")


def test_revoke_and_expire(allowlist: set[str]) -> None:
    (w,) = accept_watches(
        [prop("package")], CAMS, allowlist, [], NOW, "v2", validated=True
    ).accepted
    undone = revoke(w)
    assert undone.status == "revoked"
    assert w.status == "watching"  # pure: input not mutated
    with pytest.raises(ValueError, match="watching"):
        revoke(undone)
    later = expire([w], NOW + timedelta(hours=23))
    assert later[0].status == "watching"
    later = expire([w], NOW + timedelta(hours=24))
    assert later[0].status == "expired"
