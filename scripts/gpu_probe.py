"""H-01 GPU probe (spec 10.2, NFR-034): no GPU is used before this report says Ready.

    uv run python scripts/gpu_probe.py                      # writes eval/hardware/<gpu>.json
    uv run python scripts/gpu_probe.py --out report.json
    uv run python scripts/gpu_probe.py --burn 30            # 30 s matmul burn (needs torch)

Reads `nvidia-smi` (name, memory, driver, CUDA, temperature, clocks, power), then checks
torch.cuda when torch is importable (otherwise reports `torch: not installed`), and
writes a JSON report with `ready: true/false` and the reasons. Runs without torch.
The report holds no hostname, user name or serial number.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIELDS = (
    ("name", str),
    ("memory_total_mib", int),
    ("memory_free_mib", int),
    ("memory_used_mib", int),
    ("driver_version", str),
    ("temperature_c", int),
    ("clocks_sm_mhz", int),
    ("clocks_max_sm_mhz", int),
    ("power_draw_w", float),
    ("pstate", str),
)
QUERY = (
    "name,memory.total,memory.free,memory.used,driver_version,temperature.gpu,"
    "clocks.sm,clocks.max.sm,power.draw,pstate"
)
MIN_FREE_MIB = 16 * 1024  # a SAM 3.1 video chunk plus headroom (spec 10.1)
MAX_BURN_TEMP_C = 85


def _num(text: str, kind: type):
    text = text.strip()
    if kind is str:
        return text
    try:
        return kind(float(text))
    except ValueError:
        return None  # "[N/A]" and friends


def parse_smi(text: str) -> list[dict]:
    rows = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(FIELDS):
            continue
        rows.append({name: _num(v, kind) for (name, kind), v in zip(FIELDS, parts, strict=True)})
    return rows


def run_smi(smi: str) -> tuple[list[dict], str | None, str | None]:
    """Return (rows, cuda_version, error)."""
    exe = shutil.which(smi)
    if exe is None:
        return [], None, f"nvidia-smi not found ({smi!r} is not on PATH)"
    try:
        q = subprocess.run(
            [exe, f"--query-gpu={QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20, check=False,
        )  # fmt: skip
        head = subprocess.run([exe], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as err:
        return [], None, f"nvidia-smi failed: {err}"
    if q.returncode != 0:
        return [], None, f"nvidia-smi exited {q.returncode}: {q.stderr.strip()[:200]}"
    return parse_smi(q.stdout), cuda_version_from(head.stdout), None


def cuda_version_from(header: str) -> str | None:
    """CUDA version from the nvidia-smi banner ("CUDA Version" or newer "CUDA UMD Version")."""
    m = re.search(r"CUDA (?:UMD )?Version:\s*([\d.]+)", header)
    return m.group(1) if m else None


def torch_info() -> dict | None:
    try:
        import torch
    except ImportError:
        return None
    info: dict = {"version": torch.__version__, "cuda": torch.version.cuda}
    info["cuda_available"] = bool(torch.cuda.is_available())
    info["device_count"] = torch.cuda.device_count() if info["cuda_available"] else 0
    if info["cuda_available"]:
        info["device_name"] = torch.cuda.get_device_name(0)
        free, total = torch.cuda.mem_get_info(0)
        info["free_mib"] = free // (1024 * 1024)
        info["total_mib"] = total // (1024 * 1024)
    return info


def burn(seconds: float, smi: str) -> dict:
    """Matrix-multiply burn on GPU 0, sampling temperature and clocks (torch required)."""
    import torch

    n = 8192
    a = torch.randn(n, n, device="cuda", dtype=torch.float16)
    b = torch.randn(n, n, device="cuda", dtype=torch.float16)
    samples: list[dict] = []
    iters = 0
    start = time.perf_counter()
    next_sample = start
    while time.perf_counter() - start < seconds:
        _ = a @ b
        iters += 1
        if time.perf_counter() >= next_sample:
            torch.cuda.synchronize()
            rows, _, _ = run_smi(smi)
            if rows:
                samples.append(
                    {k: rows[0][k] for k in ("temperature_c", "clocks_sm_mhz", "power_draw_w")}
                )
            next_sample += 2.0
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    temps = [s["temperature_c"] for s in samples if s["temperature_c"] is not None]
    clocks = [s["clocks_sm_mhz"] for s in samples if s["clocks_sm_mhz"] is not None]
    return {
        "seconds": round(elapsed, 1),
        "tflops": round(2 * n**3 * iters / elapsed / 1e12, 1),
        "max_temp_c": max(temps) if temps else None,
        "min_clock_mhz": min(clocks) if clocks else None,
        "max_clock_mhz": max(clocks) if clocks else None,
        "samples": samples,
    }


def build_report(
    smi_rows: list[dict],
    cuda_version: str | None,
    torch_info: dict | None,
    burn_result: dict | None = None,
    smi_error: str | None = None,
) -> dict:
    reasons: list[str] = []
    if smi_error:
        reasons.append(smi_error)
    if not smi_rows and not smi_error:
        reasons.append("nvidia-smi reported no GPU")
    if torch_info is None:
        reasons.append(
            "torch not installed: cannot confirm CUDA from Python (install the gpu extra)"
        )
    elif not torch_info.get("cuda_available"):
        reasons.append(f"torch {torch_info.get('version')} has no CUDA device available")
    elif (torch_info.get("free_mib") or 0) < MIN_FREE_MIB:
        reasons.append(f"free VRAM {torch_info.get('free_mib')} MiB < {MIN_FREE_MIB} MiB")
    if burn_result is not None:
        t = burn_result.get("max_temp_c")
        if t is not None and t >= MAX_BURN_TEMP_C:
            reasons.append(f"burn reached {t} C (limit {MAX_BURN_TEMP_C} C)")
    return {
        "probe": "H-01",
        "probed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "gpus": smi_rows,
        "cuda_driver_version": cuda_version,
        "torch": torch_info if torch_info is not None else "not installed",
        "burn": burn_result if burn_result is not None else "not run",
        "ready": not reasons,
        "reasons": reasons,
    }


def default_name(report: dict) -> str:
    if not report["gpus"]:
        return "no-gpu"
    name = str(report["gpus"][0]["name"])
    m = re.search(r"\b(\d{4})\b", name)
    if m:
        return m.group(1)
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "gpu"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", type=Path, help="report path (default eval/hardware/<gpu>.json)")
    ap.add_argument("--burn", type=float, default=0.0, help="seconds of matmul burn (torch only)")
    ap.add_argument("--smi", default="nvidia-smi", help="nvidia-smi executable")
    args = ap.parse_args(argv)

    rows, cuda, err = run_smi(args.smi)
    tinfo = torch_info()
    burn_result = None
    if args.burn > 0:
        if tinfo and tinfo.get("cuda_available"):
            burn_result = burn(args.burn, args.smi)
        else:
            print("burn skipped: needs torch with CUDA", file=sys.stderr)
    report = build_report(rows, cuda, tinfo, burn_result, err)
    out = args.out or REPO / "eval" / "hardware" / f"{default_name(report)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"report written to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
