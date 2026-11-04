"""One-step camera setup (FR-030): find Reolink cameras on the LAN and map them to cameras.yaml.

1. **Find**: Reolink MAC prefixes in the ARP table, plus any host answering on the Baichuan
   port 9000 (the protocol the Reolink app uses; it is on even when HTTP and RTSP are off).
2. **Identify**: log in with the shared ``REOLINK_USER`` / ``REOLINK_PASSWORD`` and read each
   device's model and the name the owner gave it in the Reolink app (HTTP API, LAN only).
3. **Match**: the model family must agree (a Duo is never a doorbell), then the device name's
   words (left, right, porch, back...) pick between cameras of the same family. A tie is left
   for the owner; the setup never guesses between two identical cameras.
4. **Write**: only ``REOLINK_*_HOST`` lines in ``.env``. Credentials are never printed or written.

Battery cameras sleep and do not answer on Wi-Fi; they use import mode (FR-031).
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict

from vigil.reolink.probe import (
    PASSWORD_ENV,
    USER_ENV,
    ReolinkUnavailable,
    import_reolink_host,
    redact,
)

REOLINK_OUIS = ("d0:76:02", "ec:71:db")
BAICHUAN_PORT = 9000

_ARP_LINE = re.compile(
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\)?\s+(?:at|ether)\s+(?P<mac>[0-9a-fA-F]{1,2}(?::[0-9a-fA-F]{1,2}){5})"
)
_WORDS = re.compile(r"[a-z]+")
_TOKENS = {
    "left",
    "right",
    "front",
    "back",
    "backyard",
    "porch",
    "door",
    "doorbell",
    "side",
    "passage",
    "garage",
    "drive",
    "driveway",
    "patio",
    "garden",
}
_ALIASES = {
    "entrance": "door",
    "entry": "door",
    "yard": "backyard",
    "rear": "back",
    # Spanish app names
    "izquierda": "left",
    "izquierdo": "left",
    "derecha": "right",
    "derecho": "right",
    "frente": "front",
    "frontal": "front",
    "delantera": "front",
    "puerta": "door",
    "entrada": "door",
    "timbre": "doorbell",
    "trasero": "back",
    "trasera": "back",
    "atras": "back",
    "lateral": "side",
    "costado": "side",
    "pasillo": "passage",
    "cochera": "garage",
    "garaje": "garage",
    "jardin": "garden",
}


class Device(BaseModel):
    """What the LAN says about one Reolink device. Never carries credentials."""

    model_config = ConfigDict(frozen=True)

    ip: str
    mac: str | None = None
    model: str | None = None
    name: str | None = None
    rtsp_enabled: bool | None = None
    error: str | None = None


class Assignment(BaseModel):
    camera_id: str
    host_env: str
    ip: str
    device_name: str | None
    device_model: str | None


class Plan(BaseModel):
    assigned: list[Assignment]
    unmatched: list[Device]
    missing: list[str]


# ---------------------------------------------------------------------------
# Find
# ---------------------------------------------------------------------------


def _mac(raw: str) -> str:
    return ":".join(part.zfill(2) for part in raw.lower().split(":"))


def arp_table(text: str) -> dict[str, str]:
    """IP -> MAC for every resolved entry of ``arp -an`` (macOS) or ``arp -n`` (Linux)."""
    return {m["ip"]: _mac(m["mac"]) for m in _ARP_LINE.finditer(text)}


def reolink_from_arp(text: str) -> dict[str, str]:
    """The ARP entries whose MAC prefix belongs to Reolink. Some Wi-Fi models use their
    radio vendor's prefix instead, so port 9000 is the second signal."""
    return {ip: mac for ip, mac in arp_table(text).items() if mac.startswith(REOLINK_OUIS)}


async def scan_port(
    hosts: Iterable[str], port: int = BAICHUAN_PORT, timeout: float = 1.5, limit: int = 256
) -> list[str]:
    """Hosts that accept a TCP connection on ``port``, in input order."""
    gate = asyncio.Semaphore(limit)

    async def one(host: str) -> bool:
        async with gate:
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
            except (OSError, TimeoutError):
                return False
            writer.close()
            return True

    hosts = list(hosts)
    hits = await asyncio.gather(*(one(h) for h in hosts))
    return [h for h, ok in zip(hosts, hits, strict=True) if ok]


def subnet_hosts(cidr: str) -> list[str]:
    """Every host address of a private subnet (refuses public ranges and anything over /20)."""
    net = ipaddress.ip_network(cidr, strict=False)
    if not net.is_private or net.prefixlen < 20:
        raise ValueError(f"refusing to scan {cidr}: only private subnets of /20 or smaller")
    return [str(ip) for ip in net.hosts()]


# ---------------------------------------------------------------------------
# Identify
# ---------------------------------------------------------------------------


def _describe(err: Exception) -> str:
    if isinstance(err, httpx.TimeoutException):
        return "unreachable (timed out): the camera may be asleep or HTTP is off"
    if isinstance(err, httpx.ConnectError):
        return "unreachable (connection refused): HTTP API off; enable it in the Reolink app"
    return redact(f"{type(err).__name__}: {err}")


def _first(payload: object) -> dict:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return {}


async def _call(client: httpx.AsyncClient, base: str, cmd: str, body: dict, token=None) -> dict:
    params = {"cmd": cmd} if token is None else {"cmd": cmd, "token": token}
    resp = await client.post(f"{base}/cgi-bin/api.cgi", params=params, json=[body])
    resp.raise_for_status()
    return _first(resp.json())


async def _identify_at(client: httpx.AsyncClient, base: str, ip: str, mac: str | None) -> Device:
    user, password = os.environ[USER_ENV], os.environ[PASSWORD_ENV]
    login = await _call(
        client,
        base,
        "Login",
        {
            "cmd": "Login",
            "param": {"User": {"Version": "0", "userName": user, "password": password}},
        },
    )
    token = (login.get("value") or {}).get("Token", {}).get("name")
    if login.get("code") != 0 or not token:
        detail = (login.get("error") or {}).get("detail", "rejected")
        return Device(ip=ip, mac=mac, error=redact(f"login failed: {detail}"))
    try:
        info = await _call(client, base, "GetDevInfo", {"cmd": "GetDevInfo"}, token)
        dev = (info.get("value") or {}).get("DevInfo", {})
        ports = await _call(client, base, "GetNetPort", {"cmd": "GetNetPort"}, token)
        net = (ports.get("value") or {}).get("NetPort", {})
        rtsp = net.get("rtspEnable")
        return Device(
            ip=ip,
            mac=mac,
            model=dev.get("model") or None,
            name=dev.get("name") or None,
            rtsp_enabled=None if rtsp is None else bool(rtsp),
        )
    finally:
        with contextlib.suppress(httpx.HTTPError, ValueError):
            await _call(client, base, "Logout", {"cmd": "Logout"}, token)


async def _identify_baichuan(ip: str, mac: str | None, host_cls) -> Device:
    """Model and app name over port 9000 only (``bc_only``): works with HTTP and RTSP off."""
    host = host_cls(ip, os.environ[USER_ENV], os.environ[PASSWORD_ENV], bc_only=True)
    try:
        await asyncio.wait_for(host.get_host_data(), 40)
        return Device(ip=ip, mac=mac, model=host.camera_model(0), name=host.camera_name(0))
    finally:
        with contextlib.suppress(Exception):
            await host.logout()


async def identify(ip: str, mac: str | None = None, timeout: float = 5.0, host_cls=None) -> Device:
    """Model, app name and RTSP state of one device. Errors come back as a redacted message.

    Tries the HTTP API first; when it is off, falls back to the Baichuan protocol through
    reolink-aio (optional group ``reolink``; ``host_cls`` replaces its Host class in tests).
    """
    missing = [name for name in (USER_ENV, PASSWORD_ENV) if not os.environ.get(name)]
    if missing:
        return Device(ip=ip, mac=mac, error=f"set {' and '.join(missing)} in .env")
    last: Exception | None = None
    # LAN cameras use self-signed certificates; the host comes from the local ARP table.
    async with httpx.AsyncClient(verify=False, timeout=timeout) as client:  # noqa: S501
        for scheme in ("https", "http"):
            try:
                return await _identify_at(client, f"{scheme}://{ip}", ip, mac)
            except (httpx.HTTPError, ValueError) as err:
                last = err
    if host_cls is None:
        try:
            host_cls = import_reolink_host()
        except ReolinkUnavailable:
            return Device(ip=ip, mac=mac, error=_describe(last))
    try:
        return await _identify_baichuan(ip, mac, host_cls)
    except Exception as err:  # reolink-aio raises its own hierarchy; report, never crash
        return Device(ip=ip, mac=mac, error=f"port 9000: {_describe(err)}")


# ---------------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------------


def family(model: str | None) -> str | None:
    m = (model or "").lower()
    if not m:
        return None
    if "doorbell" in m:
        return "doorbell"
    if "duo" in m:
        return "duo"
    if "argus" in m and "pt" in m.split():
        return "argus_pt"
    if "argus" in m:
        return "argus"
    if "trackmix" in m:
        return "trackmix"
    return "other"


def _tokens(*texts: str | None) -> set[str]:
    words = set()
    for text in texts:
        for w in _WORDS.findall((text or "").replace("_", " ").lower()):
            w = _ALIASES.get(w, w)
            if w in _TOKENS:
                words.add(w)
    if "doorbell" in words:
        words.add("door")
    return words


def _score(device: Device, cam: Mapping) -> int | None:
    want, have = family(cam.get("model")), family(device.model)
    if want is not None and have is not None and want != have:
        return None
    base = 10 if want is not None and want == have else 1
    shared = _tokens(device.name) & _tokens(cam.get("name"), cam.get("id"))
    return base + 3 * len(shared)


def match(
    devices: Iterable[Device], cameras: Iterable[Mapping], pins: Mapping[str, str] | None = None
) -> Plan:
    """Assign identified devices to cameras; ambiguous pairs are left for the owner.

    ``pins`` (camera id -> IP) are the owner's own answers and are applied first.
    """
    devices = [d for d in devices if d.error is None]
    cameras = [c for c in cameras if c.get("host_env")]
    pins = dict(pins or {})
    unknown = [cid for cid in pins if cid not in {c["id"] for c in cameras}]
    if unknown:
        raise ValueError(f"unknown camera id(s) in pins: {unknown}")
    scores = {
        (d.ip, c["id"]): s for d in devices for c in cameras if (s := _score(d, c)) is not None
    }
    by_ip = {d.ip: d for d in devices}
    by_id = {c["id"]: c for c in cameras}
    assigned = [
        Assignment(
            camera_id=cid,
            host_env=by_id[cid]["host_env"],
            ip=ip,
            device_name=by_ip[ip].name if ip in by_ip else None,
            device_model=by_ip[ip].model if ip in by_ip else None,
        )
        for cid, ip in pins.items()
    ]
    free_dev = {d.ip for d in devices} - set(pins.values())
    free_cam = {c["id"] for c in cameras} - set(pins)
    held: set[str] = set()
    for (ip, cid), s in sorted(scores.items(), key=lambda kv: -kv[1]):
        if ip not in free_dev or cid not in free_cam or ip in held:
            continue
        rivals = [
            k for k, v in scores.items()
            if v == s and k != (ip, cid) and (
                (k[0] == ip and k[1] in free_cam) or (k[1] == cid and k[0] in free_dev)
            )
        ]  # fmt: skip
        if rivals:
            held.update({ip} | {k[0] for k in rivals})
            free_cam -= {cid} | {k[1] for k in rivals}
            continue
        dev, cam = by_ip[ip], by_id[cid]
        assigned.append(
            Assignment(
                camera_id=cid,
                host_env=cam["host_env"],
                ip=ip,
                device_name=dev.name,
                device_model=dev.model,
            )
        )
        free_dev.discard(ip)
        free_cam.discard(cid)
    taken = {a.camera_id for a in assigned}
    return Plan(
        assigned=sorted(assigned, key=lambda a: a.camera_id),
        unmatched=[d for d in devices if d.ip in free_dev],
        missing=[c["id"] for c in cameras if c["id"] not in taken],
    )


def camera_rows(cfg) -> list[dict]:
    """The fields ``match`` needs from a loaded cameras.yaml config."""
    return [
        {
            "id": c.id,
            "name": c.name,
            "model": getattr(c, "model", None),
            "host_env": c.source.host_env if c.source else None,
            "power_profile": getattr(c, "power_profile", None),
        }
        for c in cfg.cameras
    ]


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def update_env(path: Path, hosts: Mapping[str, str]) -> list[str]:
    """Set ``REOLINK_*_HOST`` lines in a .env file, leaving every other line untouched."""
    bad = [k for k in hosts if not re.fullmatch(r"REOLINK_[A-Z0-9_]+_HOST", k)]
    if bad:
        raise ValueError(f"only REOLINK_*_HOST keys may be written, not {bad}")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    changed, seen = [], set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in hosts and not line.lstrip().startswith("#"):
            seen.add(key)
            new = f"{key}={hosts[key]}"
            if line != new:
                lines[i] = new
                changed.append(key)
    for key, value in hosts.items():
        if key not in seen:
            lines.append(f"{key}={value}")
            changed.append(key)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed
