# Standalone Reolink Wi-Fi filming sessions

Evidence: FIXTURE tests only. No camera has been contacted for this implementation.
`reolink-aio==0.22.0` is the existing optional dependency pin; installed with
`uv sync --extra reolink`. No go2rtc or model weights are needed.

Set each camera's `source.stream` to `sub`, `main`, or `ext` in cameras.yaml. Hosts and
credentials belong only in .env. For filming, use the Reolink app to set main to **1080p,
H.264, 2–4 Mbps**. Vigil does not change camera settings. Battery cameras are refused.

After the owner supplies hosts and credentials, these are **CMD** commands, to be run
only for an approved filming session:

```cmd
uv run vigil reolink probe --camera front
uv run vigil reolink capture --camera front --out-dir data\segments
```

Omit `--camera front` to include all configured cameras. Stop capture with **Ctrl+C**
when the session ends. Capture reads the selected RTSP stream directly by default; no
24/7 task or startup service is installed. Probe resolves URLs using the pinned SDK's
`get_rtsp_stream_source`, reports the selected encoding, configured bits/s and fps, and
the SDK's Wi-Fi signal in dBm. Below −70 dBm is flagged. Unsupported signal values remain
unavailable, not invented. Stream reachability is checked independently with ffprobe.

Raw segments stay in gitignored data/. Ingest still requires privacy polygons (or the
explicit owner declaration `privacy: none_needed`) and produces masked, silent windows.
