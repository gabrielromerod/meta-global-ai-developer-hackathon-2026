# Vigil readiness — Nov 3, 2026

The requested software is implemented with **REAL logic / FIXTURE acceptance**. No requirement is upgraded to real-data Verified. Inter is selected. The owner confirmed **no Home Hub**, so side_left, backyard_1 and backyard_2 use timestamped imported clips and never continuous streams.

## Current release gate

- **FIXTURE:** all seven React wave tasks have independent APPROVED reviews. Root integrated the actual API, shared state, cached cited chat, browser-local household messages, real video/overlays/clock/3D/citations, decoded snapshots, phone voice encoding and guarded point selection.
- **FIXTURE:** post-cutover full offline backend **1,543 passed** (170.96s); full browser suite **45 passed** locally (86.57s) and against the reviewed Docker sandbox (86.64s). Frontend **134 tests** and production build pass; Ruff check/format pass. Earlier Linux full offline run passed1,543 with networking disabled before the mechanical cutover. Exact start/end times are in [timing.md](timing.md).
- **FIXTURE:** both fresh final reviewers returned **APPROVED** in round two (A:cde38c03, B:80e217f0). Cutover060c583c serves the exact reviewed React build at `/` and `/next/`; legacy consumer source/runtime is removed. The private LAN calibration worksheet remains separate. Reviewer A also APPROVED the mechanical cutover (9e3aa161). See [review ledger](react-review-ledger.md).
- **FIXTURE:** the132-state root-route layout smoke covers all11 exact CSS viewports in both themes with zero document overflow, page errors or healthy-network failures;132 PNGs pass unchanged provenance/decode/audio/metadata checks. See `qa/screens/060c583c/` and the independent full interaction matrices under `qa/reviews/final-a/` and `qa/reviews/final-b/`. This is CSS-viewport evidence, not physical-device certification.
- **MISSING — hosted CI confirmation:** CI wiring is implemented; local Windows/Linux/Docker gates pass. Hosted execution has not run. The repository is private and remaining free Actions quota could not be read with current OAuth scopes; any potentially billed run needs the owner's spending decision. No extra OAuth access was requested.

## Seven-camera backend

| Requested item | Status and evidence |
| --- | --- |
| ExifTool and CI metadata gate | **REAL logic / FIXTURE:** ExifTool13.59 installed; shared fail-closed scanner handles GPS/EXIF/XMP/device data, malformed/missing tools, Windows batching and GLB embedded resources. `test_metadata_scan.py`, `test_point_privacy.py`, CI metadata steps. Demo currently has zero camera media; that empty scan is not footage acceptance. |
| Real inventory, rings and noise | **REAL logic / FIXTURE:** seven Wi-Fi cameras, only left passage to backyard, right trees are a barrier, only doorbell egress, unknown transit times. Outer-only activity never starts/escalates a visit. `test_real_home.py`, `test_topology.py`, `test_consumer_api.py`. |
| Duo and night handling | **REAL logic / FIXTURE:** full1920px detection, per-half nominal curved geometry/homography, larger seam/edge uncertainty, same-camera reacquisition, no plate OCR. Colour/IR/mixed is logged with its inference basis. `test_panorama.py`, generated panoramic MP4 cloud test. Physical lighting behavior remains unverified. |
| Anti-doxxing/privacy/export | **REAL logic / FIXTURE:** sky/ridgeline/curb/opposite-property/watermark template masks, exact review digest, audio rejection, metadata stripping and every-frame generated Duo checks. All seven real cameras remain blocked. `test_privacy_review.py`, `test_upload_boundaries.py`, `test_session_export.py`. |
| Battery import/Hub | **REAL logic / FIXTURE:** no-Hub mode, explicit timestamped import, source retained/no overwrite, Hub-aware SDK adapter, battery stream refusal and battery-wake/clock gaps. `test_battery_import.py`. No device was contacted. |
| AC capture and disk safety | **REAL logic / FIXTURE:** sub-ring/main event clips, pre-roll pins, unique partial attempts, H.2641080–1440/2–4Mbps profile, unknown truncation gap, durable pin/free-space/retention logic. `test_event_capture.py`, capture/retention tests. Hardware throughput/endurance remains unmeasured. |
| Doctor | **REAL logic / FIXTURE:** power/Hub/import/privacy/clock drift above2s/ExifTool checks without a network probe. `test_doctor.py`. READY means configured, not authenticated or camera-accepted. |
| UI data APIs | **REAL logic / FIXTURE:** actual bundle/config state, historical event dates/street counts, visits, notifications, clips, intersecting search, exact cited chat events, generic public massing and guarded exported stills. `test_consumer_api.py`, actual API/generated-media React E2E. |

The standalone field-calibration worksheet is an existing LAN maintenance utility, separate from the consumer app. Its real stills/world measurements remain field work. Public React never fetches imported private GLB; local import/validation/coordinate-transform backend tests remain intact.

## Owner input and acceptance still missing

- **MISSING — real privacy approval:** a private real still and exact approved polygons for every camera, including sky/ridgeline/curb/timestamp/watermark coverage. Templates are not approval. Re-aiming or panning/tilting requires a new review; keep PT cameras at the reviewed aim. Do not connect cameras merely to clear this list.
- **MISSING — field calibration:** addresses/firmware and approved connection, measured clock offsets, panorama ground homographies, actual field transit walk and real clip/coverage checks. Transit remains explicitly unmeasured and unsafe links fail closed.
- **MISSING — model acceptance/spending:** successful explicitly approved Meta smoke responses and provider billing/latency checks. Keys/credits/billing configuration must be supplied privately by the owner. No Meta call or spending is authorized by these software tests.
- **MISSING — consented voice audio:** config/audio_fixtures.json still has no actual owner recordings. Sample buttons use labelled cached transcripts; recorder tests use synthetic PCM and fake devices only.
- **MISSING — production measurements:** real-camera precision/recall, night matching, clock endurance, Wi-Fi failure behavior, clip latency and physical-device performance. Authored telemetry is not a measured benchmark.
- **REAL existing scope:** Expected Windows/check-ins persist in SQLite. Point objects and confirmed rule drafts remain the existing server-session catalogue, explicitly labelled as such; they are not represented as a permanent owner-configuration save. The capture configuration remains the source for processing sessions.
- **STUB / outside this rebuild:** local SAM/open weights, optional point-cloud reconstruction and Glimmer/server/GPU acceptance remain upstream work requiring owner-approved ML installs/hardware. The tested cloud chain and GLB import path are implemented; no torch/weights/go2rtc was installed here.

## Execution incident and remediation

**REAL:** one unapproved Meta `/v1/responses` HTTP POST occurred in a negative point-prompt test before its transport/privacy guard was fixed. It used an invalid sentinel key and generated black JPEG pixels. Meta returned HTTP401; no inference succeeded and no owner key was used. The exact wall-clock timestamp was not captured. The prior blanket statement of zero Meta requests is superseded by this incident. No camera connection occurred.

**REAL remediation / FIXTURE evidence:** default tests now reject unmocked Python HTTP before transport, point prompts require explicit privacy context, and real-camera review is checked before model-client construction. The negative test also rejects client creation, enables cache-only and uses a closed loopback model base. Evidence: `test_unmocked_default_http_is_blocked_before_transport`, `test_point_prompt_requires_explicit_privacy_context`, `test_point_backend_rejects_unreviewed_real_camera_before_model`.

The running Root QA server asserts constructed Settings for sandbox/cache-only/closed-loopback/invalid sentinel before launch. Its isolated ledger contains zero model-call rows. Use the correctly prefixed Windows commands in [seven-camera setup](runbooks/seven-camera-setup.md). Historical schedules and earlier judging-budget decisions are not fresh authorization for a model call.
