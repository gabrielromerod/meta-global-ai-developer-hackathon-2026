"""Session clock to local wall time (spec 9.3: times are seconds on the aligned session clock).

`zoneinfo` needs the IANA database. Linux and macOS ship it; Windows needs the `tzdata`
package, which is not a dependency yet. When the zone cannot be loaded we fall back to the
session start's own UTC offset, which is exact for any session that does not cross a DST
change (every recorded evening in this project). The fallback is logged once per zone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger(__name__)

_UTC_NAMES = {"UTC", "Etc/UTC", "Z", "GMT", "Etc/GMT"}


@lru_cache(maxsize=32)
def _zone(name: str) -> tzinfo | None:
    if name in _UTC_NAMES:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("time zone %r unavailable (install tzdata); using session offset", name)
        return None


def resolve_tz(name: str, fallback: tzinfo | None = None) -> tzinfo:
    """The named zone, else `fallback`; raises if neither is available."""
    tz = _zone(name)
    if tz is not None:
        return tz
    if fallback is not None:
        return fallback
    raise ValueError(f"time zone {name!r} unavailable and no fallback offset given")


def to_local(session_start: datetime, t: float, tz: str) -> datetime:
    """Wall-clock local time of session second `t`."""
    if session_start.tzinfo is None or session_start.utcoffset() is None:
        raise ValueError("session_start must be timezone-aware")
    zone = resolve_tz(tz, session_start.tzinfo)
    return (session_start + timedelta(seconds=t)).astimezone(zone)


def to_session(session_start: datetime, wall: datetime) -> float:
    """Session seconds of an aware wall-clock datetime."""
    return (wall - session_start).total_seconds()


def format_clock(dt: datetime) -> str:
    """'10:14 PM' style, the form the stories use."""
    return f"{(dt.hour % 12) or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
