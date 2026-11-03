# Runbook: DGX Spark phase D-1 (conditional)

Spec: [10.4](../spec/vigil-spec.md#104-advance-notice-dgx-spark-phase-d-1-conditional-not-yet-triggered). Diagram: [compute plan](../architecture/README.md#10-compute-plan-rtx-3090-first-dgx-spark-only-if-a-gate-fails).

**Status: OFF by default, not triggered.** **Blocked-by: DGX** (the DGX Spark connected to the home network) and **owner** (connecting it, SSH key, licence acceptance).

## When it runs

Only if **all** of these hold:

1. [Gate H-02](gpu-h01-h04.md#gate-h-02-mon-2200-pt) **fails** at Mon 22:00 PT, and
2. G1 has passed (footage and API-SAM parity fixtures exist), and
3. the owner has received the notice (at least 10 hours ahead) and connected the Spark by **Tue 08:00 PT**.

Window: Tue Nov 3, 08:00 to 12:00 PT. Nothing else waits on it.

## Why

SAM 3.1 video memory grows with the frames tracked. If 2 to 3 s chunks on the 3090's 24 GB cause ID switches or cannot keep up, the Spark's 128 GB of unified memory holds full 10 s windows at full resolution. Trade-off: its memory bandwidth is 273 GB/s ([StorageReview](https://www.storagereview.com/review/nvidia-dgx-spark-review-the-ai-appliance-bringing-datacenter-capabilities-to-desktops)), so it may be slower per frame. **It fixes a capacity problem, not a speed problem.**

Never used for Muse Spark Open (816B parameters; does not fit). Not planned: Glimmer at 8-bit or BF16.

## Setup

1. Ethernet (10GbE port) on the home network with a fixed address.
2. SSH key from the workstation; no password login.
3. DGX OS (Ubuntu, Arm64). Run an NGC PyTorch container for Arm64, plus the sam3 repo and the SAM 3.1 checkpoint (licence accepted).
4. A small `sam-worker` service with the same interface as the local backend: `POST /track` with a window file. Reachable **only from the workstation's address** (firewall rule), never from the internet.
5. Sync **masked** windows only, with rsync. Raw segments never leave the workstation.
6. On the workstation set `VIGIL_SAM_BACKEND=remote` and `VIGIL_SAM_URL=http://<spark-ip>:<port>`.

## Validation

Run H-02's windows on the Spark:

| Check | Pass when |
| --- | --- |
| Memory | No out-of-memory failure on 10 s windows |
| Identity | ID switches at most the API's |
| Parity | Mean IoU with the API at least 0.8 |
| Speed | Seconds per window recorded |

**If it is not better than the API on the metric that failed, stay on the API and power the Spark down.** Record the result in EVAL.md and in a `eval/hardware/dgx-spark.json` probe report (NFR-034: no GPU used before a probe confirms it).

## Shut down

- Set `VIGIL_SAM_BACKEND` back to `api` or `local`.
- Stop `sam-worker`; delete synced windows from the Spark.
