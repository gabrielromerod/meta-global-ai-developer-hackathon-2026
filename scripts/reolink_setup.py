"""Find the Reolink cameras on this LAN, identify them and fill the REOLINK_*_HOST lines in .env.

    uv run python scripts/reolink_setup.py                      # find, identify, show the plan
    uv run python scripts/reolink_setup.py --subnet 10.99.4.0/22 --host 10.99.4.60
    uv run python scripts/reolink_setup.py --pin front_left_duo=10.99.4.52  # settle a tie
    uv run python scripts/reolink_setup.py --write              # also update .env (hosts only)

Needs REOLINK_USER and REOLINK_PASSWORD in .env (the Reolink app account for the cameras).
Credentials are never printed. Battery cameras sleep and will not answer; they use import mode.
See vigil/reolink/setup.py for the method.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vigil.reolink import setup as rs


def _arp() -> str:
    try:
        return subprocess.run(
            ["arp", "-an"], capture_output=True, text=True, timeout=10, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


async def _wake(hosts: list[str]) -> None:
    """Touch every host once so sleepy Wi-Fi devices land in the ARP table."""
    await rs.scan_port(hosts, port=rs.BAICHUAN_PORT, timeout=1.0, limit=512)


async def discover(subnets: list[str], extra: list[str]) -> dict[str, str | None]:
    pool = [h for s in subnets for h in rs.subnet_hosts(s)]
    if pool:
        await _wake(pool)
    table = _arp()
    by_mac, macs = rs.reolink_from_arp(table), rs.arp_table(table)
    open_9000 = await rs.scan_port(sorted(set(pool) | set(by_mac) | set(extra)), timeout=2.0)
    found: dict[str, str | None] = {ip: macs.get(ip) for ip in open_9000}
    found.update({ip: mac for ip, mac in by_mac.items()})
    for ip in extra:
        found.setdefault(ip, None)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("config/cameras.yaml"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--subnet", action="append", default=[], help="private CIDR to sweep")
    parser.add_argument("--host", action="append", default=[], help="a camera IP you know")
    parser.add_argument("--pin", action="append", default=[], help="camera_id=IP, your answer")
    parser.add_argument("--write", action="store_true", help="write REOLINK_*_HOST to .env")
    args = parser.parse_args()

    if args.env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)
    from vigil.ingest.config import load_config

    cameras = rs.camera_rows(load_config(args.config))

    found = asyncio.run(discover(args.subnet, args.host))
    print(f"Found {len(found)} Reolink device(s) on the LAN")
    devices = asyncio.run(_identify_all(found))
    for d in devices:
        what = f"{d.model} · “{d.name}”" if d.error is None else d.error
        rtsp = "" if d.rtsp_enabled in (None, True) else "  (RTSP off: turn it on in the app)"
        print(f"  {d.ip:<15} {d.mac or '':<17}  {what}{rtsp}")

    pins = dict(p.split("=", 1) for p in args.pin)
    plan = rs.match(devices, cameras, pins=pins)
    print("\nPlan")
    for a in plan.assigned:
        print(f"  {a.camera_id:<16} <- {a.ip:<15} {a.device_name or ''}")
    for d in plan.unmatched:
        print(f"  ?                <- {d.ip:<15} {d.name or ''}: rename it in the Reolink app")
    battery = {c["id"] for c in cameras if c.get("power_profile") == "battery_wifi"}
    for cid in plan.missing:
        why = "battery camera, asleep: use import mode" if cid in battery else "not found"
        print(f"  {cid:<16}    {why}")

    if args.write and plan.assigned:
        changed = rs.update_env(args.env_file, {a.host_env: a.ip for a in plan.assigned})
        print(f"\nUpdated {args.env_file}: {', '.join(changed) or 'no changes'}")
    elif plan.assigned:
        print("\nDry run. Add --write to save these hosts to .env.")


async def _identify_all(found: dict[str, str | None]):
    return await asyncio.gather(*(rs.identify(ip, mac) for ip, mac in sorted(found.items())))


if __name__ == "__main__":
    main()
