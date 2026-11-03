# Runbook: RTX 3090 tasks H-01 to H-04

Spec: [section 10](../spec/vigil-spec.md#10-compute-plan-rtx-3090-first-dgx-spark-only-if-a-gate-fails), [10.2](../spec/vigil-spec.md#102-hardware-verification-tasks-added-to-section-9), [10.3](../spec/vigil-spec.md#103-hardware-dependency-matrix). Requirements: FR-028, FR-042, NFR-034, NFR-035. Diagram: [compute plan](../architecture/README.md#10-compute-plan-rtx-3090-first-dgx-spark-only-if-a-gate-fails).

**Blocked-by: hardware** (the RTX 3090 workstation) and **owner** (accepting the SAM 3.1 licence on Hugging Face; confirming the workstation OS). `torch` is **not** installed in the default environment; GPU code imports it lazily and tests that need it carry the `gpu` marker, which the default run excludes.

**Rule: no GPU is used before H-01 has run on it** (NFR-034). Until then `VIGIL_SAM_BACKEND=api` and `VIGIL_TRIAGE_BACKEND=spark`.

## Workstation OS (WSL2 note)

- If the workstation runs Windows, run SAM 3.1 under **WSL2 Ubuntu with CUDA** (⚠️ confirm the sam3 repository builds there).
- Run Glimmer through llama.cpp's **Windows CUDA build**, or the same WSL2.
- ffmpeg on Windows comes from winget; Vigil resolves it through `ffmpeg_bin()`. Inside WSL2, install ffmpeg with the distribution's package manager.

## H-01 GPU probe

| Item | Value |
| --- | --- |
| Due | Mon Nov 2, 12:30 PT |
| Runs | `scripts/gpu_probe.py`: `nvidia-smi`, driver, CUDA, `torch.cuda` check, free VRAM, a 30 s matrix-multiply burn to confirm clocks and temperatures |
| Output | `eval/hardware/3090.json` (committed) |
| Done when | The 3090 is marked **Ready** or **Not ready** |

Commit the report even if it says Not ready; that is evidence too.

## H-02 Local SAM 3.1 benchmark

| Item | Value |
| --- | --- |
| Due | Mon Nov 2, 22:00 PT (**gate**) |
| Setup | Install the sam3 repo; download the SAM 3.1 checkpoint (licence accepted on Hugging Face by the owner) |
| Runs | Image prompt test, then video chunks of 2, 3, 5 and 10 s at 640 and 960 px, 5 and 10 fps, on masked windows only |
| Output | Table of peak VRAM, seconds per window, out-of-memory failures; chosen chunk settings, in EVAL.md |

Memory risk is real: one RTX 4090 (24 GB) ran out of memory on SAM 3.1 video after 16 of 63 frames ([sam3 issue 511](https://github.com/facebookresearch/sam3/issues/511)). Vigil already stitches overlapping windows (FR-007), so the 3090 tracks 2 to 3 s chunks with 1 s overlap at reduced resolution.

### Gate H-02 (Mon 22:00 PT)

The 3090 **passes** if:

1. a 10 s window from one camera, processed in chunks, finishes in **10 s or less** (keeps up with live), and
2. chunking adds **no more than 1 ID switch per window** compared with the API.

| Outcome | Action |
| --- | --- |
| Pass | `VIGIL_SAM_BACKEND=local` for live home mode and the benchmark; the DGX Spark stays off |
| Fail | Live mode and benchmark fall back to API SAM (costed in [spec 11](../spec/vigil-spec.md#11-meta-api-credit-plan-150)); phase [D-1](dgx-spark-d1.md) becomes optional and the owner gets the notice at least 10 hours before the Spark would be needed |

## H-03 Local Glimmer benchmark

| Item | Value |
| --- | --- |
| Due | Tue Nov 3, 12:00 PT |
| Runs | llama.cpp server with Muse Glimmer 30B 4-bit GGUF (about 17 GB per [Unsloth](https://unsloth.ai/docs/models/muse-glimmer)) and the vision projector; 20 triage fixtures |
| Output | Tokens per second, peak VRAM, JSON-valid rate, agreement with Spark on the 20 fixtures |
| Enables | `VIGIL_TRIAGE_BACKEND=glimmer` (FR-028) |

**SAM and Glimmer never share the GPU.** Glimmer's 17 GB plus a SAM chunk will not fit together. Live home mode runs local SAM with Spark triage (API); the benchmark runs the SAM pass first, then a separate Glimmer triage pass.

## H-04 Local versus API SAM parity

| Item | Value |
| --- | --- |
| Due | Tue Nov 3, 12:00 PT |
| Runs | The same 20 masked windows through both backends (API side is billed: `live` marker, budget guard on) |
| Output | Mean mask IoU and ID-switch counts |
| Target | Mean IoU at least 0.8 ⚠️, pre-registered in [EVAL.md](../../EVAL.md) (NFR-035) |

## Results go to

- `eval/hardware/*.json` (H-01), EVAL.md tables (H-02 to H-04), and the requirement checklists (FR-028, FR-042, NFR-034, NFR-035).
