# Runbook: Reolink cameras

Task: **T-04** (done by **Mon 13:45 PT**, first in the daylight block), then T-05 (14:30) and T-26. Requirements: FR-030, FR-031, FR-032, FR-001 and FR-008 (zone kinds), NFR-029, NFR-031. Spec: [section 6](../spec/vigil-spec.md#6-reolink-integration-real-world-environment).

**Blocked-by: hardware.** Needs the 4 home cameras on the home network and the owner's admin access. Open item from the spec: the 4 camera models, and whether an NVR or Home Hub is used.

## 0. Before you start

- [ ] Every camera is bound to **local** login (a camera bound only to a Reolink cloud account has no local login until switched).
- [ ] A unique password, and a low-privilege user if the model supports user roles (⚠️ check per model).
- [ ] Credentials go only into `.env` on the edge machine (`REOLINK_USER`, `REOLINK_PASSWORD`, `REOLINK_<CAMERA>_HOST`); see `.env.example`. Never in `config/cameras.yaml`, a commit, a log line or a screenshot.

## 1. Hardware compatibility

| Camera type | Continuous stream | On-camera AI events | Fit for Vigil |
| --- | --- | --- | --- |
| PoE or plug-in Wi-Fi | Yes (RTSP main and sub) | Yes | Full support |
| On a Reolink NVR | Yes, per channel | Yes, through the NVR | Full support |
| Battery (Argus, Altas) | Only through a Home Hub or NVR; **preview drops after 5 min** | Through Hub or NVR | Event clips only, not continuous |
| LTE (Go series) | Not supported by the Home Assistant integration | No | **Not usable** |
| Bound to a Reolink cloud account | No local login until switched | No | Switch to local first |

A battery camera on any side turns that side into event clips only: record it in `config/cameras.yaml` and in [readiness](../readiness.md), and expect gaps on that side. Sources: [Reolink RTSP introduction](https://support.reolink.com/hc/en-us/articles/900000630706-Introduction-to-RTSP/), [Home Assistant Reolink integration](https://www.home-assistant.io/integrations/reolink/).

## 2. Probe

```sh
uv run vigil reolink probe        # FR-030; reads hosts and credentials from .env
```

The probe reports model, firmware, RTSP or FLV reachability and AI-event support for each camera. Pass: all 4 cameras reachable, credentials absent from the output and the logs. Save the report (with hosts redacted) for the T-04 issue.

## 3. Stream URLs

| Stream | URL shape | Use |
| --- | --- | --- |
| RTSP main | `rtsp://<user>:<pass>@<ip>:554/Preview_01_main` | Processing; re-encoded to 1280 px H.264 at 10 fps for SAM 3.1. Up to 4K H.265 on some models; RTSP is the only protocol that carries 4K |
| RTSP sub | `rtsp://<user>:<pass>@<ip>:554/Preview_01_sub` | Motion gate and live view (H.264, low resolution) |
| NVR channel N | `Preview_0N_main`, `Preview_0N_sub` | Same, per channel |
| FLV | `http://<ip>/flv?port=1935&app=bcs&stream=channel0_main.bcs&user=<user>&password=<pass>` ⚠️ | Lightest protocol on the camera; fallback if RTSP connections drop |

⚠️ The FLV URL shape is not in the spec; it follows the form used by the Home Assistant integration. Confirm it against your camera before relying on it. Some older models name RTSP paths `h264Preview_01_main`; the probe reports which path answers.

Never paste a URL with credentials into a terminal history you share, an issue or a log. Use the `.env` variables.

## 4. On-camera privacy masks (first privacy layer)

1. In the Reolink app or web UI, open each camera's **Privacy Mask** settings ([Reolink guide](https://support.reolink.com/hc/en-us/articles/360003493454--How-to-Set-up-Privacy-Mask-for-Reolink-Cameras)).
2. Draw rectangles over the street, neighbouring houses and windows, and the house number. The **side cameras** are the most likely to see neighbours.
3. Save. On-camera masks apply to live view and recordings.
4. Vigil's exact polygons (FR-003, `privacy` in `config/cameras.yaml`) remain the second layer; both are required.

### VLC mask check (⚠️ required)

The spec flags that it is not yet confirmed whether the RTSP stream carries the on-camera mask.

1. Open VLC → Media → Open Network Stream → the RTSP main URL (typed, not saved in history).
2. Confirm the masked rectangles are black in the stream itself.
3. Repeat for the sub stream.
4. Record the result per camera in the T-04 issue. If a stream does not carry the mask, Vigil's polygons are the only layer for that stream: tighten them and re-run the privacy scan.

## 5. Zone kinds to draw (FR-001, FR-008)

Spatial origin roles (FR-044) depend on each zone's `kind` in `config/cameras.yaml`. Draw them on a still of each camera while you are at it, and keep zone names unique across cameras. Format: `zone_name: {kind: <kind>, polygon: [[x, y], ...]}` in the processed 1280 px frame; a plain polygon list loads as `interior_yard`.

| Kind | Draw it over | Example (spec 9.4) |
| --- | --- | --- |
| `egress` | A door **of the house itself**, where a person steps out into view | `front_door_egress` (front), `back_door_egress` (backyard) |
| `perimeter` | Where outsiders enter the property: street edge, driveway entry, side alley | `driveway_entry` (front), `side_alley` (side_left) |
| `interior_yard` | Everything else: porch, lawn, paths | `porch` (front) |

- A **garage door**, or any opening an outsider can reach without first appearing on a camera, is `interior_yard`, never `egress`.
- A person's origin is the zone holding their foot point in most of their first 10 frames (1 s). A track starting mid-yard has no origin and counts as `unknown`, which fails closed (rules for non-household still fire).
- Keep the egress polygons tight around the door: a track re-born there within 10 min of a non-egress person last seen on the door area (polygon dilated by 50%) loses its egress origin.
- `uv run pytest tests/unit/test_config.py -q` checks the kinds and names; an unknown kind fails with the line number.

## 6. Audio off

- Turn audio recording **off** on every camera for the hackathon period.
- ffmpeg removes audio again during capture (`-an`) and the privacy check refuses any window with an audio stream (NFR-002).
- Verify: `ffprobe` on a captured segment shows no audio stream.

## 7. Restreamer (go2rtc)

Browsers cannot play RTSP, so the LAN app uses go2rtc (WebRTC or MSE). It also holds one connection per camera, which reduces camera load.

- Config: `infra/go2rtc.yaml`, with stream URLs built from environment variables, never literal credentials.
- Bind to the home network interface only. No port forwarding; no public RTSP; remote access only through a private VPN (NFR-031).
- ⚠️ Check go2rtc's licence on its repository and record it in the README credits before shipping.
- Capture (`vigil/reolink/capture.py`) reads from go2rtc and writes 10 s segments by stream copy, audio removed, into the 48 h ring under `data/` (gitignored).

## 8. Acceptance

| Check | Pass when | Requirement |
| --- | --- | --- |
| Probe | All 4 cameras pass; no credentials in output or logs | FR-030 |
| Zone kinds | Every camera's `egress` and `perimeter` zones drawn; `test_config.py` passes on `config/cameras.yaml` | FR-001, FR-008 |
| 30 min capture | No segment gap over 1 s | FR-031 (T-05) |
| 2 h capture overnight plus a cable pull | No gap over 1 s; reconnect within 30 s; average CPU logged | NFR-029, NFR-033 |
| AI events | At least 9 of 10 staged walk-ins produce an event; latency measured | FR-032 |
| Exposure | A phone on cellular reaches no camera or edge port | NFR-031, FR-034 |
